#!/usr/bin/env Rscript
# Reference round trip (plan Phase 4): a published OSP model's own simulations against the ones Modeler One
# regenerates from the imported CPF, on PK-Sim, at identical time points.
#
#   LC_ALL=en_US.UTF-8 Rscript reference_compare.R <published.json> <ours.json> <pairs.json> <work dir>
#
# pairs.json: [{"ours": <simulation>, "published": <simulation>, "offset_min": <dose time in the published one>,
#               "end_h": <window>}]. Both simulations of a pair are sampled on the same grid (the published one
# shifted by offset_min) and compared on the peripheral venous plasma concentration of the compound. Writes
# <work dir>/roundtrip.json; exits 0 whatever the differences are (they are the finding, not a crash).

suppressPackageStartupMessages({
  library(ospsuite)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 4) stop("usage: reference_compare.R <published.json> <ours.json> <pairs.json> <work dir>")
published <- normalizePath(args[[1]])
ours <- normalizePath(args[[2]])
pairs <- fromJSON(args[[3]], simplifyVector = FALSE)
work <- args[[4]]
dir.create(work, recursive = TRUE, showWarnings = FALSE)
work <- normalizePath(work)

PLASMA <- "Organism|PeripheralVenousBlood|%s|Plasma (Peripheral Venous Blood)"
RESOLUTION <- 0.25  # points per minute: one sample every 4 min on both sides
TOLERANCE <- 1e-6    # relative to the published peak: identical inputs must agree to solver precision

initPKSim()

export_models <- function(snapshot, name) {
  dir <- file.path(work, name)
  unlink(dir, recursive = TRUE)
  dir.create(dir)
  runSimulationsFromSnapshot(snapshot, output = dir, exportCSV = FALSE, exportPKML = TRUE)
  # recursive: a "/" in a simulation name ("iv 0.075 mg/kg (1 min)") becomes a subdirectory in the exported path
  files <- list.files(dir, pattern = "\\.pkml$", full.names = TRUE, recursive = TRUE)
  stats::setNames(files, sub("\\.pkml$", "", substring(files, nchar(dir) + 2)))
}

name_key <- function(x) gsub("[^A-Za-z0-9.]", "", x)

pkml_of <- function(files, sim_name) {
  rel <- names(files)
  hit <- files[endsWith(rel, paste0("-", sim_name)) | rel == sim_name]
  if (length(hit) == 0) {
    # Names with characters a file name cannot hold: compare alphanumerics only, the shortest match wins
    keys <- name_key(rel)
    cand <- which(endsWith(keys, name_key(sim_name)))
    hit <- files[cand[order(nchar(keys[cand]))]]
  }
  if (length(hit) == 0) NA_character_ else hit[[1]]
}

plasma_curve <- function(pkml, compound, start_min, end_min) {
  sim <- loadSimulation(pkml, loadFromCache = FALSE)
  clearOutputIntervals(sim)
  addOutputInterval(sim, startTime = start_min, endTime = end_min, resolution = RESOLUTION)
  clearOutputs(sim)
  path <- sprintf(PLASMA, compound)
  addOutputs(path, sim)
  results <- runSimulations(sim)[[1]]
  data <- getOutputValues(results, quantitiesOrPaths = path)$data
  list(time = data$Time, value = data[[path]])
}

compound <- fromJSON(ours, simplifyVector = FALSE)$Compounds[[1]]$Name
published_models <- export_models(published, "published")
our_models <- export_models(ours, "ours")

trapz <- function(t, y) sum(diff(t) * (head(y, -1) + tail(y, -1)) / 2)

rows <- lapply(pairs, function(pair) {
  tryCatch({
    pub <- pkml_of(published_models, pair$published)
    own <- pkml_of(our_models, pair$ours)
    if (is.na(pub) || is.na(own)) stop(sprintf("model not exported (published: %s, ours: %s)", !is.na(pub), !is.na(own)))
    end_min <- as.numeric(pair$end_h) * 60
    offset <- as.numeric(pair$offset_min)
    p <- plasma_curve(pub, compound, offset, offset + end_min)
    o <- plasma_curve(own, compound, 0, end_min)
    # Pair the samples by time (PK-Sim always adds t = 0 to the outputs, so indices do not line up when the
    # published dose is given later, e.g. the Dapagliflozin IV microdose at 60 min).
    idx <- match(round(o$time, 4), round(p$time - offset, 4))
    keep <- !is.na(idx)
    tv <- o$time[keep]
    ov <- o$value[keep]
    pv <- p$value[idx[keep]]
    peak <- max(abs(pv))
    worst <- which.max(abs(ov - pv))
    max_rel <- if (peak > 0) max(abs(ov - pv)) / peak else NA_real_
    list(
      ours = pair$ours, published = pair$published, points = length(tv),
      max_rel_to_peak = max_rel,
      worst_time_min = tv[[worst]],
      cmax_ratio = max(ov) / max(pv),
      auc_ratio = trapz(tv, ov) / trapz(tv, pv),
      identical = isTRUE(max_rel <= TOLERANCE),
      by_design = pair$by_design %||% ""
    )
  }, error = function(e) list(ours = pair$ours, published = pair$published, error = conditionMessage(e)))
})

# Input-level comparison: every parameter value of the published model against ours, for the first pair of up to
# three published simulations. Protocol/event paths are named per simulation and are left out. This locates a
# difference in the model rather than inferring it from the curves.
parameter_diffs <- list()
seen <- character(0)
for (pair in pairs) {
  if (length(seen) >= 3 || pair$published %in% seen) next
  seen <- c(seen, pair$published)
  parameter_diffs[[pair$published]] <- tryCatch({
    pub <- loadSimulation(pkml_of(published_models, pair$published), loadFromCache = FALSE)
    own <- loadSimulation(pkml_of(our_models, pair$ours), loadFromCache = FALSE)
    values <- function(sim) {
      paths <- getAllParameterPathsIn(sim)
      paths <- paths[!grepl("^(Events|Applications)\\|", paths) & !grepl("*", paths, fixed = TRUE)]
      v <- getQuantityValuesByPath(paths, sim)
      stats::setNames(as.numeric(v), paths)
    }
    a <- values(pub)
    b <- values(own)
    common <- intersect(names(a), names(b))
    rel <- abs(a[common] - b[common]) / pmax(abs(a[common]), 1e-300)
    rel[!is.finite(rel)] <- 0
    differ <- sort(rel[rel > 1e-9], decreasing = TRUE)
    top <- head(differ, 25)
    list(
      ours = pair$ours, compared = length(common), differing = length(differ),
      only_published = head(setdiff(names(a), names(b)), 25), only_ours = head(setdiff(names(b), names(a)), 25),
      top = lapply(names(top), function(k) list(path = k, published = a[[k]], ours = b[[k]]))
    )
  }, error = function(e) list(error = conditionMessage(e)))
}

report <- list(
  parameter_diffs = parameter_diffs,
  ospsuite = as.character(packageVersion("ospsuite")),
  compound = compound,
  tolerance = TOLERANCE,
  pairs = rows,
  identical = sum(vapply(rows, function(r) isTRUE(r$identical), logical(1))),
  total = length(rows)
)
write_json(report, file.path(work, "roundtrip.json"), auto_unbox = TRUE, pretty = TRUE, digits = NA, force = TRUE)
cat(sprintf("round trip %s: %d of %d simulations identical within %g of the peak\n",
            compound, report$identical, report$total, TOLERANCE))
for (name in names(parameter_diffs)) {
  d <- parameter_diffs[[name]]
  if (!is.null(d$error)) {
    cat(sprintf("parameters %s: ERROR %s\n", name, d$error))
    next
  }
  cat(sprintf("parameters %s vs %s: %d compared, %d differ, %d only published, %d only ours\n",
              name, d$ours, d$compared, d$differing, length(d$only_published), length(d$only_ours)))
  for (t in d$top) cat(sprintf("    %-90s %.10g -> %.10g\n", t$path, t$published, t$ours))
  for (p in d$only_published) cat(sprintf("    only published: %s\n", p))
  for (p in d$only_ours) cat(sprintf("    only ours: %s\n", p))
}
for (r in rows) {
  if (!is.null(r$error)) {
    cat(sprintf("  %-60s ERROR %s\n", r$ours, r$error))
  } else {
    cat(sprintf("  %-60s max|diff|/peak %.3g  AUC %.6f  Cmax %.6f  (vs %s)\n",
                r$ours, r$max_rel_to_peak, r$auc_ratio, r$cmax_ratio, r$published))
  }
}
