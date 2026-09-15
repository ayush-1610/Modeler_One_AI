#!/usr/bin/env Rscript
# Engine benchmark. Run it on every compute server to size the fitting time budget.
#
#   Rscript benchmark.R [simulation.pkml] [parameter path to vary] [batch runs] [output.json]
#
# Defaults use the Aciclovir example shipped with ospsuite, so the script runs without project data.
# It measures: model load, first and repeated single runs, SimulationBatch runs on 1 core and on all
# cores, PK analysis, and a real parameter identification (OSP example) with function-evaluation counts.

suppressPackageStartupMessages({
  library(ospsuite)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
default_pkml <- system.file("extdata", "Aciclovir.pkml", package = "ospsuite")
pkml <- if (length(args) >= 1 && nzchar(args[[1]])) args[[1]] else default_pkml
param_path <- if (length(args) >= 2 && nzchar(args[[2]])) args[[2]] else "Aciclovir|Lipophilicity"
n_runs <- if (length(args) >= 3) as.integer(args[[3]]) else 200L
out_file <- if (length(args) >= 4) args[[4]] else "benchmark_result.json"

elapsed <- function(expr) {
  start <- proc.time()[["elapsed"]]
  value <- force(expr)
  list(value = value, seconds = proc.time()[["elapsed"]] - start)
}
section <- function(name, expr) {
  cat(sprintf("== %s\n", name))
  tryCatch(expr, error = function(e) list(error = conditionMessage(e)))
}

logical_cores <- parallel::detectCores(logical = TRUE)
physical_cores <- parallel::detectCores(logical = FALSE)
result <- list(
  host = list(
    platform = R.version$platform,
    r_version = R.version.string,
    ospsuite = as.character(packageVersion("ospsuite")),
    logical_cores = logical_cores,
    physical_cores = physical_cores
  ),
  engine_api = as.list(vapply(
    c("initPKSim", "runSimulationsFromSnapshot", "convertSnapshot", "loadSimulationsFromSnapshot",
      "createSimulationBatch", "runSimulationBatches", "createIndividual", "createPopulation"),
    function(f) exists(f, envir = asNamespace("ospsuite"), inherits = FALSE),
    logical(1)
  )),
  model = list(pkml = basename(pkml), varied_parameter = param_path, batch_runs = n_runs)
)

result$single_runs <- section("single runs", {
  load <- elapsed(loadSimulation(pkml, loadFromCache = FALSE))
  sim <- load$value
  first <- elapsed(runSimulations(sim)[[1]])
  repeats <- vapply(1:5, function(i) elapsed(runSimulations(sim))$seconds, numeric(1))
  pk <- elapsed(calculatePKAnalyses(first$value))
  list(load_seconds = load$seconds, first_run_seconds = first$seconds,
       repeat_run_seconds_median = median(repeats), pk_analysis_seconds = pk$seconds)
})

result$batch <- section("simulation batch", {
  sim <- loadSimulation(pkml, loadFromCache = FALSE)
  base <- getParameter(param_path, sim)$value
  set.seed(1)
  values <- base * exp(runif(n_runs, -0.2, 0.2))
  batch <- createSimulationBatch(simulation = sim, parametersOrPaths = param_path)
  enqueue <- function() for (v in values) batch$addRunValues(parameterValues = v)

  enqueue()
  one_core <- elapsed(runSimulationBatches(batch, simulationRunOptions = SimulationRunOptions$new(numberOfCores = 1)))
  enqueue()
  workers <- max(1L, logical_cores - 1L)
  all_cores <- elapsed(runSimulationBatches(batch, simulationRunOptions = SimulationRunOptions$new(numberOfCores = workers)))
  list(
    runs = n_runs,
    one_core_seconds_per_run = one_core$seconds / n_runs,
    parallel_cores = workers,
    parallel_seconds_per_run = all_cores$seconds / n_runs,
    parallel_speedup = one_core$seconds / all_cores$seconds
  )
})

result$parameter_identification <- section("parameter identification (OSP Aciclovir example)", {
  suppressPackageStartupMessages(library(ospsuite.parameteridentification))
  sim_250 <- loadSimulation(default_pkml, loadFromCache = FALSE)
  sim_500 <- loadSimulation(default_pkml, loadFromCache = FALSE)
  dose_path <- "Events|IV 250mg 10min|Application_1|ProtocolSchemaItem|Dose"
  setParameterValues(parameters = getParameter(dose_path, sim_500), values = 500, units = "mg")

  renal_path <- "Neighborhoods|Kidney_pls_Kidney_ur|Aciclovir|Renal Clearances-TS-Aciclovir|TSspec"
  lipophilicity <- PIParameters$new(parameters = list(
    getParameter("Aciclovir|Lipophilicity", sim_250), getParameter("Aciclovir|Lipophilicity", sim_500)
  ))
  lipophilicity$minValue <- -10
  lipophilicity$maxValue <- 10
  clearance <- PIParameters$new(parameters = list(getParameter(renal_path, sim_250), getParameter(renal_path, sim_500)))
  clearance$minValue <- 0
  clearance$maxValue <- 10

  observed_file <- system.file("extdata", "Aciclovir_Profiles.xlsx", package = "ospsuite.parameteridentification")
  importer <- createImporterConfigurationForFile(filePath = observed_file)
  importer$namingPattern <- "{Source}.{Sheet}.{Dose}"
  observed <- loadDataSetsFromExcel(xlsFilePath = observed_file, importerConfigurationOrPath = importer)
  pick <- function(dose) observed[[grep(dose, names(observed), fixed = TRUE)[[1]]]]

  output_path <- "Organism|PeripheralVenousBlood|Aciclovir|Plasma (Peripheral Venous Blood)"
  mapping <- function(sim, dose) {
    m <- PIOutputMapping$new(quantity = getQuantity(path = output_path, container = sim))
    m$addObservedDataSets(pick(dose))
    m$scaling <- "log"
    m
  }

  configuration <- PIConfiguration$new()
  task <- ParameterIdentification$new(
    simulations = list(sim_250, sim_500),
    parameters = list(lipophilicity, clearance),
    outputMappings = list(mapping(sim_250, "250"), mapping(sim_500, "500")),
    configuration = configuration
  )
  run <- elapsed(task$run())
  summary <- run$value$toDataFrame()
  details <- run$value$toList()
  list(
    wall_seconds = run$seconds,
    algorithm = details$algorithm,
    function_evaluations = details$fnEvaluations,
    seconds_per_evaluation = run$seconds / max(1, as.numeric(details$fnEvaluations)),
    objective_value = details$objectiveValue,
    estimates = summary
  )
})

write_json(result, out_file, auto_unbox = TRUE, pretty = TRUE, digits = NA)
cat(toJSON(result, auto_unbox = TRUE, pretty = TRUE, digits = 6), "\n")
