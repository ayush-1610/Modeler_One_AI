#!/usr/bin/env Rscript
# Engine entrypoint: Rscript run_job.R <job.json>
#
# stdout protocol read by the worker: "PROGRESS <0..1>" and "WARNING <text>".
# Verified in the released ospsuite 12.4.4 (needs .NET 8 and LC_ALL=en_US.UTF-8): initPKSim,
# loadProjectFromSnapshot, exportProjectToSnapshot, runSimulationsFromSnapshot (Linux/Windows only, not macOS),
# loadSimulation, runSimulations(simulation, population=...), createPopulationCharacteristics/createPopulation
# (returns list(population, derivedParameters, seed)), loadPopulation/exportPopulationToCSV,
# SensitivityAnalysis$new(simulation=)/$addParameterPaths/$numberOfSteps/$variationRange, runSensitivityAnalysis,
# SensitivityAnalysisRunOptions$new()/$numberOfCores/$showProgress, exportSensitivityAnalysisResultsToCSV,
# createSimulationBatch(simulation, parametersOrPaths, moleculesOrPaths) + $addRunValues(parameterValues, initialValues)
# + runSimulationBatches (returns list keyed by batch id then run id), exportResultsToCSV, calculatePKAnalyses,
# exportPKAnalysesToCSV. convertSnapshot is deprecated. Golden tests in the engine image (golden/golden_roundtrip.R,
# golden/golden_tasks.R, golden/pi_smoke.R) must pass before an image is qualified (F-405).

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

# The plasma output the platform selects for every simulation (matches builder.PLASMA_OUTPUT_PATH).
PLASMA_TEMPLATE <- "Organism|PeripheralVenousBlood|%s|Plasma (Peripheral Venous Blood)"

# Normalize the OSP result CSVs runSimulationsFromSnapshot wrote into the canonical bundle the campaign reads:
# {"profiles": {<SimulationName>: {times_min, concentrations, path, unit}}}. Keying by simulation name (which
# the platform sets to the study id) avoids depending on PK-Sim's CSV file naming. NOTE: the CSV file <-> sim
# mapping is derived from the file name; confirm PK-Sim's naming on the Linux engine (F-405 golden run).
write_profiles <- function(snapshot_path, out_dir) {
  snap <- fromJSON(snapshot_path, simplifyVector = FALSE)
  all_csvs <- list.files(out_dir, pattern = "\\.csv$", full.names = TRUE)
  all_csvs <- all_csvs[!grepl("pk_analys", basename(all_csvs), ignore.case = TRUE)]
  # PK-Sim's runSimulationsFromSnapshot writes one file per simulation named "<snapshot>-<SimName>-Results.csv"
  # (plus an outputs.csv index); prefer those, and fall back to any CSV if the naming ever changes.
  result_csvs <- all_csvs[grepl("-Results\\.csv$", basename(all_csvs))]
  if (length(result_csvs) == 0) result_csvs <- all_csvs[basename(all_csvs) != "outputs.csv"]
  sims <- snap$Simulations
  profiles <- list()

  for (sim in sims) {
    sim_name <- sim$Name
    compound <- if (length(sim$Compounds)) sim$Compounds[[1]]$Name else NA_character_
    plasma_path <- if (!is.na(compound)) sprintf(PLASMA_TEMPLATE, compound) else ""

    csv <- result_csvs[endsWith(basename(result_csvs), paste0("-", sim_name, "-Results.csv"))]
    if (length(csv) == 0) csv <- result_csvs[basename(tools::file_path_sans_ext(result_csvs)) == sim_name]  # "<SimName>.csv"
    if (length(csv) == 0) csv <- result_csvs[endsWith(basename(tools::file_path_sans_ext(result_csvs)), paste0("-", sim_name))]
    if (length(csv) == 0 && length(sims) == 1 && length(result_csvs) == 1) csv <- result_csvs
    if (length(csv) == 0) {
      cat("WARNING ", sprintf("no results CSV found for simulation '%s'", sim_name), "\n", sep = "")
      next
    }

    # Read the header and the numeric data separately: the unit (e.g. "µmol/l") is multibyte and the numeric
    # rows are ASCII, so this parses correctly regardless of the process locale and matches columns by name.
    lines <- readLines(csv[[1]], encoding = "UTF-8", warn = FALSE)
    lines <- lines[nzchar(lines)]
    header <- sub("^\xef\xbb\xbf", "", lines[[1]], useBytes = TRUE)  # strip a UTF-8 BOM (byte-wise; locale-safe)
    col_names <- scan(text = header, what = "character", sep = ",", quote = "\"", quiet = TRUE)
    data <- read.csv(text = lines[-1], header = FALSE, colClasses = "numeric")
    names(data) <- col_names
    if ("IndividualId" %in% col_names) data <- data[data[["IndividualId"]] == data[["IndividualId"]][[1]], , drop = FALSE]

    time_col <- grep("^Time ", col_names, value = TRUE)
    conc_col <- col_names[startsWith(col_names, plasma_path)]
    if (length(conc_col) == 0) {  # fall back to the only non-Time/Id column
      others <- setdiff(col_names, c(time_col, "IndividualId"))
      if (length(others) == 1) conc_col <- others
    }
    if (length(time_col) == 0 || length(conc_col) == 0) {
      cat("WARNING ", sprintf("could not locate time/plasma columns for '%s'", sim_name), "\n", sep = "")
      next
    }
    unit <- sub(".*\\[(.*)\\]$", "\\1", conc_col[[1]])
    profiles[[sim_name]] <- list(
      times_min = as.numeric(data[[time_col[[1]]]]),
      concentrations = as.numeric(data[[conc_col[[1]]]]),
      path = plasma_path,
      unit = unit
    )
  }

  write_json(list(profiles = profiles), file.path(out_dir, "profiles.json"), auto_unbox = TRUE, digits = NA)
  profiles
}

run_task <- function() {
  task <- job$task
  # PK-Sim is only needed to build models/populations from scratch; loading a pkml and running
  # simulations/sensitivity/batches are ospsuite Core operations that do not require the PK-Sim database.
  if (task %in% c("simulate", "dry_run", "convert_to_project", "population")) initPKSim()
  progress(0.05)

  if (identical(task, "simulate")) {
    snapshot <- input_path("snapshot.json")
    runSimulationsFromSnapshot(
      snapshot,
      output = out_dir,
      exportCSV = TRUE,
      exportPKML = isTRUE(job$options$export_pkml)
    )
    progress(0.9)
    profiles <- write_profiles(snapshot, out_dir)  # canonical bundle the campaign's evaluate_round reads
    return(list(profiles = as.list(names(profiles))))
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
  if (identical(task, "population")) {
    # Run one simulation across a virtual population. The population is either supplied as a PK-Sim
    # population CSV input, or built here from a demographic spec (options$population).
    sim <- loadSimulation(input_path("simulation.pkml"))
    if (any(vapply(job$inputs, function(i) identical(i$name, "population.csv"), logical(1)))) {
      population <- loadPopulation(input_path("population.csv"))
    } else {
      p <- job$options$population
      # JSON round-trips whole numbers as R integers, but the .NET bindings want Nullable<Double> for the
      # weight/height/age/percentage ranges; coerce so PK-Sim does not reject an Int32 for a Double property.
      dbl <- function(x) if (is.null(x)) NULL else as.numeric(x)
      characteristics <- createPopulationCharacteristics(
        species = if (!is.null(p$species)) p$species else Species$Human,
        population = p$population, numberOfIndividuals = as.integer(p$number_of_individuals),
        proportionOfFemales = if (!is.null(p$proportion_of_females)) dbl(p$proportion_of_females) else 50,
        weightMin = dbl(p$weight_min), weightMax = dbl(p$weight_max),
        heightMin = dbl(p$height_min), heightMax = dbl(p$height_max),
        ageMin = dbl(p$age_min), ageMax = dbl(p$age_max),
        seed = if (!is.null(job$options$seed)) as.integer(job$options$seed) else NULL
      )
      created <- createPopulation(characteristics)
      population <- created$population
    }
    progress(0.2)
    exportPopulationToCSV(population, file.path(out_dir, "population.csv"))  # the exact individuals that ran
    results <- runSimulations(sim, population = population)[[1]]
    progress(0.85)
    exportResultsToCSV(results, file.path(out_dir, "results.csv"))
    exportPKAnalysesToCSV(calculatePKAnalyses(results), file.path(out_dir, "pk_analyses.csv"))
    vpc <- job$options$vpc
    if (!is.null(vpc)) {
      # Visual predictive check band (MS-01 S1/S2/S4): percentiles of the output across the population at each
      # simulated time, so the campaign can test how many observed points fall inside the 5-95 % band.
      out <- getOutputValues(results, quantitiesOrPaths = vpc$output_path)$data
      value_col <- setdiff(names(out), c("IndividualId", "Time"))[1]
      probs <- if (!is.null(vpc$percentiles)) as.numeric(unlist(vpc$percentiles)) else c(0.05, 0.5, 0.95)
      times <- sort(unique(out$Time))
      bands <- lapply(probs, function(q) vapply(times, function(t) {
        stats::quantile(out[[value_col]][out$Time == t], probs = q, names = FALSE, na.rm = TRUE)
      }, numeric(1)))
      names(bands) <- sprintf("%g", probs * 100)
      write_json(list(output_path = vpc$output_path, individuals = population$count, times_min = times,
                      percentiles = bands),
                 file.path(out_dir, "vpc.json"), auto_unbox = TRUE, digits = NA)
    }
    return(list(individuals = population$count))
  }
  if (identical(task, "sensitivity")) {
    # Local sensitivity of the PK parameters to the listed model parameters.
    sim <- loadSimulation(input_path("simulation.pkml"))
    paths <- as.character(unlist(job$options$parameter_paths))
    if (length(paths) == 0) stop("sensitivity task needs options.parameter_paths")
    analysis <- SensitivityAnalysis$new(simulation = sim)
    analysis$addParameterPaths(paths)
    if (!is.null(job$options$number_of_steps)) analysis$numberOfSteps <- as.integer(job$options$number_of_steps)
    if (!is.null(job$options$variation_range)) analysis$variationRange <- as.numeric(job$options$variation_range)
    options <- SensitivityAnalysisRunOptions$new()
    if (!is.null(job$options$number_of_cores)) options$numberOfCores <- as.integer(job$options$number_of_cores)
    options$showProgress <- FALSE
    progress(0.2)
    results <- runSensitivityAnalysis(analysis, options)
    progress(0.85)
    exportSensitivityAnalysisResultsToCSV(results, file.path(out_dir, "sensitivity.csv"))
    return(list(parameters = as.list(paths), steps = analysis$numberOfSteps))
  }
  if (identical(task, "batch")) {
    # Evaluate many scenarios by varying the listed parameters over a set of runs (one SimulationBatch,
    # kept warm across runs). options.parameter_paths lists the paths; options.runs[i] gives the aligned
    # parameter values (and optional molecule initial values) for run i.
    sim <- loadSimulation(input_path("simulation.pkml"))
    param_paths <- as.character(unlist(job$options$parameter_paths))
    molecule_paths <- if (!is.null(job$options$molecule_paths)) as.character(unlist(job$options$molecule_paths)) else NULL
    batch <- createSimulationBatch(simulation = sim, parametersOrPaths = param_paths, moleculesOrPaths = molecule_paths)
    runs <- job$options$runs
    if (length(runs) == 0) stop("batch task needs options.runs")
    # SimulationBatch takes values in each parameter's BASE unit. options.parameter_units (aligned with the paths,
    # "" for dimensionless) says which unit the run values are in, and they are converted here — the same trap as
    # parameter identification, where values given "in cm/min" were silently applied as dm/min.
    units <- if (!is.null(job$options$parameter_units)) as.character(unlist(job$options$parameter_units)) else NULL
    to_base <- function(values) {
      if (is.null(units)) return(values)
      vapply(seq_along(values), function(k) {
        if (nzchar(units[[k]])) toBaseUnit(getParameter(param_paths[[k]], sim), values[[k]], units[[k]]) else values[[k]]
      }, numeric(1))
    }
    run_ids <- character(length(runs))
    for (i in seq_along(runs)) {
      values <- to_base(as.numeric(unlist(runs[[i]]$parameter_values)))
      initials <- if (!is.null(runs[[i]]$initial_values)) as.numeric(unlist(runs[[i]]$initial_values)) else NULL
      run_ids[[i]] <- batch$addRunValues(parameterValues = values, initialValues = initials)
    }
    progress(0.2)
    batch_results <- runSimulationBatches(list(batch))[[batch$id]]
    progress(0.85)
    index <- list()
    for (i in seq_along(runs)) {
      results <- batch_results[[run_ids[[i]]]]
      csv_name <- sprintf("batch-%03d-results.csv", i)
      exportResultsToCSV(results, file.path(out_dir, csv_name))
      index[[i]] <- list(run = i, run_id = run_ids[[i]], parameter_values = runs[[i]]$parameter_values, results = csv_name)
    }
    write_json(list(parameter_paths = as.list(param_paths), runs = index),
               file.path(out_dir, "batch_index.json"), auto_unbox = TRUE, digits = NA)
    return(list(runs = length(runs)))
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
