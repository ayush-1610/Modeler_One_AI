#!/usr/bin/env Rscript
# Engine entrypoint: Rscript run_job.R <job.json>
#
# stdout protocol read by the worker: "PROGRESS <0..1>" and "WARNING <text>".
# Verified in the released ospsuite 12.4.4 (needs .NET 8 and LC_ALL=en_US.UTF-8): initPKSim,
# loadProjectFromSnapshot, exportProjectToSnapshot, runSimulationsFromSnapshot (Linux/Windows only, not macOS),
# createSimulationBatch, runSimulationBatches. convertSnapshot is deprecated. Golden tests in the engine image
# (golden/golden_roundtrip.R, golden/pi_smoke.R) must pass before an image is qualified (F-405).

suppressPackageStartupMessages({
  library(jsonlite)
  library(digest)
  library(ospsuite)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1) stop("usage: run_job.R <job.json>")
script_dir <- dirname(normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE))))
job <- fromJSON(args[[1]], simplifyVector = FALSE)
out_dir <- job$outputs_dir
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

progress <- function(fraction) {
  cat(sprintf("PROGRESS %.3f\n", fraction))
  flush(stdout())
}

input_path <- function(name) {
  for (item in job$inputs) {
    if (identical(item$name, name)) {
      actual <- digest(file = item$path, algo = "sha256")
      if (!identical(actual, item$sha256)) stop(sprintf("sha256 mismatch for %s", name))
      return(item$path)
    }
  }
  stop(sprintf("job has no input named '%s'", name))
}

write_manifest <- function(extra = list()) {
  manifest <- c(
    list(
      ospsuite_version = as.character(packageVersion("ospsuite")),
      r_version = R.version.string,
      platform = R.version$platform,
      session_info = capture.output(sessionInfo())
    ),
    extra
  )
  write_json(manifest, file.path(out_dir, "engine_manifest.json"), auto_unbox = TRUE, pretty = TRUE)
}

run_task <- function() {
  task <- job$task
  if (task %in% c("simulate", "dry_run", "convert_to_project")) initPKSim()
  progress(0.05)

  if (identical(task, "simulate")) {
    runSimulationsFromSnapshot(
      input_path("snapshot.json"),
      output = out_dir,
      exportCSV = TRUE,
      exportPKML = isTRUE(job$options$export_pkml)
    )
    return(list())
  }
  if (task %in% c("dry_run", "convert_to_project")) {
    # Builds the PK-Sim project from the snapshot without solving; fails if PK-Sim cannot load the snapshot.
    loadProjectFromSnapshot(input_path("snapshot.json"), output = out_dir, runSimulations = FALSE)
    return(list(projects = list.files(out_dir, pattern = "\\.pksim5$")))
  }
  if (identical(task, "pk_analysis")) {
    simulation <- loadSimulation(input_path("simulation.pkml"))
    results <- runSimulations(simulation)[[1]]
    progress(0.7)
    exportResultsToCSV(results, file.path(out_dir, "results.csv"))
    exportPKAnalysesToCSV(calculatePKAnalyses(results), file.path(out_dir, "pk_analyses.csv"))
    return(list())
  }
  if (identical(task, "parameter_identification")) {
    source(file.path(script_dir, "run_pi.R"))
    spec <- fromJSON(input_path("pi_spec_base.json"), simplifyVector = FALSE)
    for (i in seq_along(spec$simulations)) {
      spec$simulations[[i]]$pkml <- input_path(spec$simulations[[i]]$pkml)
    }
    starts <- job$options$start_values
    for (i in seq_along(spec$parameters)) {
      value <- starts[[spec$parameters[[i]]$name]]
      if (!is.null(value)) spec$parameters[[i]]$start <- value
    }
    spec$start_index <- job$options$start_index
    spec$seed <- job$options$seed
    spec_path <- file.path(out_dir, "pi_spec.json")  # exported with the results: the exact spec this start ran
    write_json(spec, spec_path, auto_unbox = TRUE, pretty = TRUE, digits = NA)
    run_parameter_identification(spec_path, out_dir)
    return(list())
  }
  stop(sprintf("task '%s' is not implemented by this engine image", task))
}

extra <- withCallingHandlers(
  run_task(),
  warning = function(w) {
    cat("WARNING ", conditionMessage(w), "\n", sep = "")
    invokeRestart("muffleWarning")
  }
)
progress(0.95)
write_manifest(extra)
progress(1)
