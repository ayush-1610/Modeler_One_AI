#!/usr/bin/env Rscript
# Golden test for the T-09 engine tasks: population, sensitivity, batch.
# Drives run_job.R as a subprocess (exactly as the worker does) against a pkml exported from the example
# snapshot, and asserts each task's canonical outputs exist and are well-formed. Run inside the engine image
# (or on a qualified engine host); must pass before an image is qualified (F-405).
#
#   Rscript services/engine-worker/golden/golden_tasks.R
#
# Exit status 0 = all tasks passed; non-zero on the first failure.

suppressPackageStartupMessages({
  library(jsonlite)
  library(digest)
  library(ospsuite)
})

repo <- normalizePath(file.path(dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE))), "..", "..", ".."))
run_job <- file.path(repo, "services", "engine-worker", "r", "run_job.R")
snapshot <- file.path(repo, "services", "engine-worker", "golden", "example_snapshot.json")
stopifnot(file.exists(run_job), file.exists(snapshot))

fail <- function(...) { cat("FAIL:", ..., "\n"); quit(status = 1) }
ok <- function(...) cat("ok:", ..., "\n")

# --- export a pkml the tasks can load ------------------------------------------------------------
initPKSim()
staging <- tempfile("golden_tasks_"); dir.create(staging)
runSimulationsFromSnapshot(snapshot, output = staging, exportCSV = FALSE, exportPKML = TRUE)
pkml <- list.files(staging, pattern = "\\.pkml$", full.names = TRUE)[[1]]
sim <- loadSimulation(pkml)
# the compound name is the 3rd segment of the plasma output path (Organism|PeripheralVenousBlood|<compound>|Plasma...)
plasma <- sim$outputSelections$allOutputs[[1]]$path
compound <- strsplit(plasma, "\\|")[[1]][[3]]
# vary the compound's lipophilicity: a constant physicochemical parameter that drives the plasma profile
logp_path <- paste0(compound, "|Lipophilicity")
cat("compound:", compound, "\nusing parameter path:", logp_path, "\n")

# --- helper: run one job through run_job.R and return its outputs dir ----------------------------
run <- function(task, options = list(), extra_inputs = list()) {
  work <- tempfile("job_"); dir.create(work)
  outdir <- file.path(work, "outputs"); dir.create(outdir)
  inputs <- c(
    list(list(name = "simulation.pkml", path = pkml, sha256 = digest(file = pkml, algo = "sha256"))),
    extra_inputs
  )
  job <- list(job_id = paste0("golden-", task), task = task, inputs = inputs, options = options, outputs_dir = outdir)
  job_file <- file.path(work, "job.json")
  write_json(job, job_file, auto_unbox = TRUE, digits = NA)
  status <- system2("Rscript", c(run_job, job_file), stdout = TRUE, stderr = TRUE)
  code <- attr(status, "status")
  if (!is.null(code) && code != 0) { cat(paste(status, collapse = "\n"), "\n"); fail(task, "engine exited non-zero") }
  outdir
}

# --- population ----------------------------------------------------------------------------------
pop_out <- run("population", options = list(
  seed = 123,
  population = list(population = HumanPopulation$European_ICRP_2002, number_of_individuals = 6,
                    proportion_of_females = 50, weight_min = 60, weight_max = 90, age_min = 20, age_max = 60)
))
for (f in c("population.csv", "results.csv", "pk_analyses.csv", "engine_manifest.json")) {
  if (!file.exists(file.path(pop_out, f))) fail("population missing", f)
}
pop_csv <- read.csv(file.path(pop_out, "population.csv"), check.names = FALSE)
if (nrow(pop_csv) != 6) fail("population expected 6 individuals, got", nrow(pop_csv))
res <- read.csv(file.path(pop_out, "results.csv"), check.names = FALSE)
if (length(unique(res$IndividualId)) != 6) fail("population results cover", length(unique(res$IndividualId)), "individuals, expected 6")
ok("population: 6 individuals simulated, results + PK exported")

# --- sensitivity ---------------------------------------------------------------------------------
sens_out <- run("sensitivity", options = list(parameter_paths = list(logp_path), number_of_steps = 3, variation_range = 0.1))
if (!file.exists(file.path(sens_out, "sensitivity.csv"))) fail("sensitivity missing sensitivity.csv")
sens <- read.csv(file.path(sens_out, "sensitivity.csv"), check.names = FALSE)
if (nrow(sens) == 0) fail("sensitivity.csv is empty")
ok("sensitivity:", nrow(sens), "rows exported for 1 parameter x PK parameters")

# --- batch ---------------------------------------------------------------------------------------
batch_out <- run("batch", options = list(
  parameter_paths = list(logp_path),
  runs = list(list(parameter_values = list(1.0)), list(parameter_values = list(2.0)), list(parameter_values = list(3.0)))
))
idx_file <- file.path(batch_out, "batch_index.json")
if (!file.exists(idx_file)) fail("batch missing batch_index.json")
idx <- fromJSON(idx_file, simplifyVector = FALSE)
if (length(idx$runs) != 3) fail("batch expected 3 runs, got", length(idx$runs))
for (r in idx$runs) if (!file.exists(file.path(batch_out, r$results))) fail("batch missing results for run", r$run)
# the three logP values should give distinguishable concentration profiles
peaks <- vapply(idx$runs, function(r) {
  d <- read.csv(file.path(batch_out, r$results), check.names = FALSE)
  max(d[[ncol(d)]])
}, numeric(1))
if (length(unique(round(peaks, 6))) < 2) fail("batch runs produced identical peaks; parameter variation had no effect")
ok("batch: 3 runs, distinct peaks", paste(signif(peaks, 4), collapse = ", "))

cat("\nGOLDEN TASKS PASSED\n")
