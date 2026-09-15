#!/usr/bin/env Rscript
# Golden round trip for an engine image (feature F-405):
#   platform snapshot -> PK-Sim project -> snapshot again (content compared); run from snapshot and compute PK
#   (Linux only: ospsuite 12.4.4 does not support runSimulationsFromSnapshot on macOS); DataSet API probe.
#
#   LC_ALL=en_US.UTF-8 Rscript golden_roundtrip.R <snapshot.json> <work dir>

suppressPackageStartupMessages({
  library(ospsuite)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) stop("usage: golden_roundtrip.R <snapshot.json> <work dir>")
snapshot <- normalizePath(args[[1]])
work <- args[[2]]
dir.create(work, recursive = TRUE, showWarnings = FALSE)
work <- normalizePath(work)
is_macos <- identical(Sys.info()[["sysname"]], "Darwin")

report <- list(ospsuite = as.character(packageVersion("ospsuite")), os = Sys.info()[["sysname"]], snapshot = basename(snapshot))
step <- function(name, expr) {
  start <- proc.time()[["elapsed"]]
  outcome <- tryCatch({
    value <- force(expr)
    list(ok = TRUE, value = value)
  }, error = function(e) list(ok = FALSE, error = conditionMessage(e)))
  outcome$seconds <- round(proc.time()[["elapsed"]] - start, 3)
  report[[name]] <<- outcome
  cat(sprintf("%-26s %s (%.2fs)\n", name, if (outcome$ok) "OK" else paste("FAILED:", outcome$error), outcome$seconds))
  outcome$ok
}
new_dir <- function(name) {
  path <- file.path(work, name)
  unlink(path, recursive = TRUE)
  dir.create(path, recursive = TRUE)
  path
}

step("init_pksim", {
  initPKSim()
  "initialized"
})

projects <- character(0)
if (is_macos) {
  # ospsuite 12.4.4 on macOS: loadProjectFromSnapshot terminates R with a segmentation fault, also for OSP's
  # own library snapshots (verified with Dapagliflozin-Model.json). Verified on Linux instead.
  report$snapshot_to_project <- list(ok = NA, skipped = "loadProjectFromSnapshot crashes on macOS in ospsuite 12.4.4; verified on Linux")
  cat(sprintf("%-26s SKIPPED on macOS (Linux engine runs it)\n", "snapshot_to_project"))
} else {
  project_dir <- new_dir("project")
  step("snapshot_to_project", {
    loadProjectFromSnapshot(snapshot, output = project_dir)
    list.files(project_dir)
  })
  projects <- list.files(project_dir, pattern = "\\.pksim5$", full.names = TRUE)
}

if (length(projects) > 0) {
  back_dir <- new_dir("snapshot_back")
  if (step("project_to_snapshot", {
    exportProjectToSnapshot(projects[[1]], output = back_dir)
    list.files(back_dir)
  })) {
    step("roundtrip_content", {
      original <- fromJSON(snapshot, simplifyVector = FALSE)
      back <- fromJSON(list.files(back_dir, pattern = "\\.json$", full.names = TRUE)[[1]], simplifyVector = FALSE)
      names_of <- function(x, key) vapply(x[[key]] %||% list(), function(item) item$Name %||% "", character(1))
      keys <- c("Compounds", "Individuals", "Protocols", "Formulations", "Simulations", "ObservedData")
      comparison <- lapply(keys, function(k) list(original = names_of(original, k), roundtrip = names_of(back, k)))
      names(comparison) <- keys
      missing <- unlist(lapply(keys, function(k) setdiff(comparison[[k]]$original, comparison[[k]]$roundtrip)))
      if (length(missing) > 0) stop(paste("lost in round trip:", paste(missing, collapse = ", ")))
      list(version_back = back$Version, building_blocks = comparison)
    })
  }
}

if (is_macos) {
  report$run_from_snapshot <- list(ok = NA, skipped = "runSimulationsFromSnapshot is not supported on macOS in ospsuite 12.4.4; verified in the Linux engine image")
  cat(sprintf("%-26s SKIPPED on macOS (Linux engine image runs it)\n", "run_from_snapshot"))
} else {
  run_dir <- new_dir("run")
  step("run_from_snapshot", {
    runSimulationsFromSnapshot(snapshot, output = run_dir, exportCSV = TRUE, exportPKML = TRUE)
    list.files(run_dir, recursive = TRUE)
  })
  for (pkml in list.files(run_dir, pattern = "\\.pkml$", full.names = TRUE, recursive = TRUE)) {
    step(paste0("pk_", tools::file_path_sans_ext(basename(pkml))), {
      simulation <- loadSimulation(pkml, loadFromCache = FALSE)
      results <- runSimulations(simulation)[[1]]
      pk <- pkAnalysesToDataFrame(calculatePKAnalyses(results))
      pk[pk$Parameter %in% c("C_max", "t_max", "AUC_inf", "t_half"), ]
    })
  }
}

step("dataset_api", {
  dataset <- DataSet$new(name = "probe")
  dataset$setValues(xValues = c(0.5, 1, 2), yValues = c(10, 20, 15), yErrorValues = c(1, 2, 1.5))
  dataset$xUnit <- "h"
  dataset$yDimension <- ospDimensions$`Concentration (mass)`
  dataset$yUnit <- "µg/l"
  dataset$yErrorType <- "ArithmeticStdDev"
  dataset$yErrorUnit <- "µg/l"
  dataset$LLOQ <- 0.5
  dataset$molWeight <- 325.8
  frame <- dataSetToDataFrame(dataset)
  if (!identical(unique(frame$yErrorUnit), unique(frame$yUnit))) stop("error unit does not match value unit")
  frame
})

write_json(report, file.path(work, "golden_report.json"), auto_unbox = TRUE, pretty = TRUE, digits = NA, force = TRUE)
failed <- names(Filter(function(x) is.list(x) && identical(x$ok, FALSE), report))
if (length(failed) > 0) {
  cat("FAILED STEPS:", paste(failed, collapse = ", "), "\n")
  quit(status = 1)
}
cat("ALL STEPS OK\n")
