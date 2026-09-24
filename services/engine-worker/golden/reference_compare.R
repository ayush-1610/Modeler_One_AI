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
  list.files(dir, pattern = "\\.pkml$", full.names = TRUE)
}

pkml_of <- function(files, sim_name) {
  hit <- files[endsWith(basename(files), paste0("-", sim_name, ".pkml"))]
  if (length(hit) == 0) hit <- files[basename(files) == paste0(sim_name, ".pkml")]
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
    n <- min(length(p$value), length(o$value))
    pv <- p$value[seq_len(n)]
    ov <- o$value[seq_len(n)]
    peak <- max(abs(pv))
    worst <- which.max(abs(ov - pv))
    max_rel <- if (peak > 0) max(abs(ov - pv)) / peak else NA_real_
    list(
      ours = pair$ours, published = pair$published, points = n,
      max_rel_to_peak = max_rel,
      worst_time_min = o$time[[worst]],
      cmax_ratio = max(ov) / max(pv),
      auc_ratio = trapz(o$time[seq_len(n)], ov) / trapz(p$time[seq_len(n)] - offset, pv),
      identical = isTRUE(max_rel <= TOLERANCE)
    )
  }, error = function(e) list(ours = pair$ours, published = pair$published, error = conditionMessage(e)))
})

report <- list(
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
for (r in rows) {
  if (!is.null(r$error)) {
    cat(sprintf("  %-60s ERROR %s\n", r$ours, r$error))
  } else {
    cat(sprintf("  %-60s max|diff|/peak %.3g  AUC %.6f  Cmax %.6f  (vs %s)\n",
                r$ours, r$max_rel_to_peak, r$auc_ratio, r$cmax_ratio, r$published))
  }
}
