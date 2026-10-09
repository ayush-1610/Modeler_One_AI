#!/usr/bin/env Rscript
# PK-Sim's own Weibull release curve, for the platform's equation to be compared against (pbpk_domain.dissolution,
# ENGINE_CONFIRMED; plan harvest rule, acceptance within 1 %).
#
#   Rscript weibull_check.R <snapshot.json> <work dir>
#
# The snapshot holds one published simulation dosing a Weibull tablet (the OSP Dapagliflozin "IC tablet (Chang 2015)":
# t50 30 min, shape 0.6, lag 0; the qualification step cuts it from golden/fixtures/Dapagliflozin-Model.json). PK-Sim
# runs it and exports its pkml; the formulation's dissolved-fraction quantity is found among the simulation's own paths
# (matched, never typed: a PK-Sim name is harvested, not invented), simulated, and written to weibull_curve.csv with the
# path it came from. No such quantity found: every application path is printed and the script fails.

suppressPackageStartupMessages({
  library(ospsuite)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) stop("usage: weibull_check.R <snapshot.json> <work dir>")
snapshot <- normalizePath(args[[1]])
work <- args[[2]]
dir.create(work, recursive = TRUE, showWarnings = FALSE)
work <- normalizePath(work)

run_dir <- file.path(work, "run")
dir.create(run_dir, showWarnings = FALSE)
runSimulationsFromSnapshot(snapshot, output = run_dir, exportCSV = FALSE, exportPKML = TRUE)
pkml <- list.files(run_dir, pattern = "\\.pkml$", full.names = TRUE, recursive = TRUE)
if (length(pkml) != 1) stop(sprintf("expected one exported simulation, found %d", length(pkml)))
sim <- loadSimulation(pkml[[1]], loadFromCache = FALSE)

# The formulation lives under the protocol's events (its Weibull parameters are at
# "Events|<protocol>|<formulation>|Dissolution time (50% dissolved)"); its dissolved fraction is a quantity whose name
# says so. Every path is searched; the 50 %-time parameter is not the fraction.
paths <- getAllQuantityPathsIn(sim)
dissolved <- paths[grepl("fraction", paths, ignore.case = TRUE) & grepl("dissolv", paths, ignore.case = TRUE) &
                   !grepl("Dissolution time", paths, fixed = TRUE)]
if (length(dissolved) == 0) {
  formulation <- paths[grepl("Chang 2015", paths, fixed = TRUE) | grepl("dissolv", paths, ignore.case = TRUE)]
  cat("no dissolved-fraction quantity; the formulation's paths:\n", paste(formulation, collapse = "\n"), "\n")
  stop("the formulation's dissolved fraction was not found")
}
cat("dissolved-fraction quantities:\n", paste(dissolved, collapse = "\n"), "\n")

clearOutputs(sim)
addOutputs(dissolved[[1]], sim)
setOutputInterval(sim, startTime = 0, endTime = 600, resolution = 1)   # 0–10 h in 1 min steps (minutes, PK-Sim's base)
results <- runSimulations(sim)[[1]]
values <- getOutputValues(results, quantitiesOrPaths = dissolved[[1]])
curve <- data.frame(time_min = values$data$Time, fraction = values$data[[dissolved[[1]]]], path = dissolved[[1]])
write.csv(curve, file.path(work, "weibull_curve.csv"), row.names = FALSE)
cat(sprintf("WEIBULL CURVE OK: %d points, fraction at 30 min = %.6f\n", nrow(curve),
            curve$fraction[which.min(abs(curve$time_min - 30))]))
