#!/usr/bin/env Rscript
# One parameter-identification start, using OSP's ospsuite.parameteridentification package (2.2.0).
#
#   Rscript run_pi.R <pi_spec.json> <output dir>
#
# The spec is written by the platform (one per start) and is itself part of the submission bundle, so a
# reviewer can re-run exactly this start. Output: <output dir>/pi_result.json.
#
# Spec fields:
#   simulations      [{id, pkml}]
#   parameters       [{name, unit, min, max, start, scale (optional), paths: [{simulation, path}]}]   one PIParameters
#                    per entry; several paths = one value shared across simulations; scale "log" optimises the
#                    parameter on log10 of its value (bounds above 0), absent or "linear" on the value itself
#   output_mappings  [{simulation, output_path, scaling ("lin"|"log"), observed: {name, time[], time_unit,
#                      values[], unit, sd[] (optional), lloq (optional), mol_weight, weight (optional)}}]
#                    weight: one residual weight for the whole dataset (the joint refinement gives every study the
#                    same say, MS-01 v1.1 SJ, D-04); absent = 1 for every point, as before
#   algorithm        "BOBYQA" | "HJKB" | "DEoptim"
#   max_evaluations  BOBYQA maxeval / HJKB maxfeval;  generations, population_size for DEoptim;  seed
#
# JSON numbers may arrive as R integers; every value handed to OSP (.NET) is converted with as.numeric().

suppressPackageStartupMessages({
  library(ospsuite)
  library(ospsuite.parameteridentification)
  library(jsonlite)
})

progress <- function(fraction) {
  cat(sprintf("PROGRESS %.3f\n", fraction))
  flush(stdout())
}

num <- function(x) as.numeric(unlist(x))

is_log_scale <- function(p) identical(p$scale, "log")

# A parameter whose fit policy is on a log scale (MS-01 §2.2: a clearance's bounds span six decades) is optimised on
# log10 of its value. ospsuite.parameteridentification 2.2.0 has no parameter transform, so this subclass applies 10^x
# to the model and reports log10 of the model's value: start, bounds, the optimiser's steps and the Hessian CI are all
# on log10, and the result is turned back to values below. Steps of one decade then weigh the same anywhere in range.
LogPIParameters <- R6::R6Class(
  "LogPIParameters",
  inherit = PIParameters,
  active = list(
    currValue = function(value) {
      if (!missing(value)) stop("currValue is read-only: use $setValue()")
      log10(ospsuite::toUnit(quantityOrDimension = private$.parameters[[1]], values = private$.parameters[[1]]$value,
                             targetUnit = private$.unit))
    }
  ),
  public = list(
    initialize = function(parameters) {
      super$initialize(parameters)
      start <- private$.startValue
      private$.startValue <- if (is.finite(start) && start > 0) log10(start) else 0
      private$.minValue <- private$.startValue - 1
      private$.maxValue <- private$.startValue + 1
    },
    setValue = function(value) super$setValue(10^value)
  )
)

build_dataset <- function(observed) {
  dataset <- DataSet$new(name = observed$name)
  sd <- if (length(observed$sd) > 0) num(observed$sd) else NULL
  dataset$setValues(xValues = num(observed$time), yValues = num(observed$values), yErrorValues = sd)
  dataset$xUnit <- observed$time_unit
  # dimension defaults to mass; a molar observed series (e.g. µmol/l, matching the simulated plasma output)
  # sets dimension "Concentration (molar)" so no MW conversion is needed.
  dim_name <- if (!is.null(observed$dimension)) observed$dimension else "Concentration (mass)"
  dataset$yDimension <- ospDimensions[[dim_name]]
  dataset$yUnit <- observed$unit
  if (!is.null(sd)) {
    dataset$yErrorType <- "ArithmeticStdDev"
    dataset$yErrorUnit <- observed$unit  # defaults to mg/l otherwise
  }
  if (!is.null(observed$lloq)) dataset$LLOQ <- as.numeric(observed$lloq)
  dataset$molWeight <- as.numeric(observed$mol_weight)
  dataset
}

algorithm_options <- function(spec) {
  switch(spec$algorithm,
    BOBYQA = {
      options <- AlgorithmOptions_BOBYQA
      if (!is.null(spec$max_evaluations)) options$maxeval <- as.numeric(spec$max_evaluations)
      options
    },
    HJKB = {
      options <- AlgorithmOptions_HJKB
      if (!is.null(spec$max_evaluations)) options$maxfeval <- as.numeric(spec$max_evaluations)
      options
    },
    DEoptim = {
      options <- AlgorithmOptions_DEoptim
      if (!is.null(spec$generations)) options$itermax <- as.numeric(spec$generations)
      if (!is.null(spec$population_size)) options$NP <- as.numeric(spec$population_size)
      options
    },
    stop(sprintf("unknown algorithm '%s'", spec$algorithm))
  )
}

# The Hessian CI's correlation matrix (rows and columns in the order of spec$parameters) as one entry per pair, keyed by
# the CPF ids; on log-scaled parameters it is the correlation of their log10. Empty when there is no CI.
correlation_pairs <- function(cor_mat, names) {
  pairs <- list()
  if (!is.matrix(cor_mat) || nrow(cor_mat) != length(names)) return(pairs)
  for (i in seq_len(length(names) - 1)) for (j in (i + 1):length(names)) {
    if (is.finite(cor_mat[i, j])) pairs[[length(pairs) + 1]] <- list(a = names[[i]], b = names[[j]], r = cor_mat[i, j])
  }
  pairs
}

run_parameter_identification <- function(spec_path, out_dir) {
  spec <- fromJSON(spec_path, simplifyVector = FALSE)
  dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
  if (!is.null(spec$seed)) set.seed(spec$seed)

  simulations <- list()
  for (s in spec$simulations) simulations[[s$id]] <- loadSimulation(s$pkml, loadFromCache = FALSE)
  progress(0.05)

  # Bounds, start and estimates are exchanged in the CPF's unit but the optimiser is driven in the parameter's BASE
  # unit: in ospsuite.parameteridentification 2.2.0 the optimiser applies values in the base unit whatever
  # PIParameters$unit says, and setting the unit does not convert the bounds (verified on the engine 2026-09-24:
  # a permeability fitted "in cm/min" was really fitted in dm/min, and stored 10x too low). So every value is
  # converted to the base unit here and back to the CPF's unit in the result. A dimensionless parameter has no
  # unit (a JSON null re-serialised by R comes back as an empty list, hence the strict string check).
  has_unit <- function(u) is.character(u) && length(u) == 1 && nzchar(u)
  base_factor <- list()  # parameter name -> multiply a base-unit value by this to get the CPF's unit
  parameters <- lapply(spec$parameters, function(p) {
    objects <- lapply(p$paths, function(x) getParameter(path = x$path, container = simulations[[x$simulation]]))
    log_scale <- is_log_scale(p)
    pi_parameter <- if (log_scale) LogPIParameters$new(parameters = objects) else PIParameters$new(parameters = objects)
    to_base <- function(v) if (has_unit(p$unit)) toBaseUnit(objects[[1]], as.numeric(v), p$unit) else as.numeric(v)
    if (log_scale && !(to_base(p$min) > 0)) stop(sprintf("%s: a log-scale fit needs bounds above 0", p$name))
    to_scale <- function(v) if (log_scale) log10(to_base(v)) else to_base(v)
    base_factor[[p$name]] <<- if (has_unit(p$unit)) toUnit(objects[[1]], 1, p$unit) else 1
    lo <- to_scale(p$min); hi <- to_scale(p$max)
    # Widen first, then set the start, then narrow: the setters reject a bound on the wrong side of the start.
    pi_parameter$maxValue <- max(hi, pi_parameter$maxValue)
    pi_parameter$minValue <- min(lo, pi_parameter$minValue)
    if (!is.null(p$start)) pi_parameter$startValue <- to_scale(p$start)
    pi_parameter$minValue <- lo
    pi_parameter$maxValue <- hi
    pi_parameter
  })

  mappings <- lapply(spec$output_mappings, function(m) {
    mapping <- PIOutputMapping$new(quantity = getQuantity(path = m$output_path, container = simulations[[m$simulation]]))
    dataset <- build_dataset(m$observed)
    if (!is.null(m$observed$weight)) {
      # PIOutputMapping (ospsuite.parameteridentification >= 2.1): a scalar weight per dataset, broadcast to its
      # points; the cost multiplies each residual by it before squaring
      weights <- list(as.numeric(m$observed$weight))
      names(weights) <- dataset$name
      mapping$addObservedDataSets(dataset, weights = weights)
    } else {
      mapping$addObservedDataSets(dataset)
    }
    mapping$scaling <- m$scaling
    mapping
  })

  configuration <- PIConfiguration$new()
  configuration$algorithm <- spec$algorithm
  configuration$algorithmOptions <- algorithm_options(spec)
  progress(0.1)

  task <- ParameterIdentification$new(
    simulations = unname(simulations),
    parameters = parameters,
    outputMappings = mappings,
    configuration = configuration
  )
  started <- proc.time()[["elapsed"]]
  result <- task$run()
  details <- result$toList()
  estimates <- result$toDataFrame()
  estimates <- estimates[!duplicated(estimates$group), ]

  # Map each estimated parameter back to the CPF id the platform fit (spec$parameters[[i]]$name), matched by
  # the PK-Sim parameter path, so the result is keyed by the CPF id (what apply_fit_estimates expects) rather
  # than the PK-Sim parameter name. The original name is kept as pksim_name.
  # The result reports each path prefixed with its simulation id ("<sim>|<parameter path>").
  id_by_path <- list()
  for (p in spec$parameters) for (x in p$paths) id_by_path[[paste0(x$simulation, "|", x$path)]] <- p$name

  output <- list(
    start_index = spec$start_index,
    algorithm = details$algorithm,
    convergence = details$convergence,
    objective_value = details$objectiveValue,
    function_evaluations = details$fnEvaluations,
    wall_seconds = proc.time()[["elapsed"]] - started,
    estimates = lapply(seq_len(nrow(estimates)), function(i) {
      row <- as.list(estimates[i, c("name", "path", "unit", "estimate", "sd", "cv", "lowerCI", "upperCI", "initialValue")])
      cpf_id <- id_by_path[[row$path]]
      if (!is.null(cpf_id)) {
        row$pksim_name <- row$name; row$name <- cpf_id
        # back from the base unit to the CPF's unit (linear units: absolute SD and CIs scale by the same factor)
        spec_p <- Filter(function(p) identical(p$name, cpf_id), spec$parameters)[[1]]
        factor <- base_factor[[cpf_id]]
        if (is_log_scale(spec_p)) {
          # from log10 back to values: the CI bounds transform exactly; the SD of log10 gives the lognormal CV
          z <- as.numeric(row$sd)
          for (k in c("estimate", "lowerCI", "upperCI", "initialValue")) row[[k]] <- 10^as.numeric(row[[k]])
          row$cv <- if (is.finite(z)) sqrt(exp((log(10) * z)^2) - 1) else NA_real_
          row$sd <- row$cv * row$estimate
          row$sd_log10 <- z
          row$scale <- "log"
        }
        for (k in c("estimate", "sd", "lowerCI", "upperCI", "initialValue")) row[[k]] <- as.numeric(row[[k]]) * factor
        row$base_unit <- row$unit
        row$unit <- if (has_unit(spec_p$unit)) spec_p$unit else row$unit
      }
      row
    }),
    correlations = correlation_pairs(details$ciDetails$corMat, vapply(spec$parameters, function(p) p$name, "")),
    ospsuite = as.character(packageVersion("ospsuite")),
    parameteridentification = as.character(packageVersion("ospsuite.parameteridentification"))
  )
  # no CI (and so no correlations) when the covariance matrix is not positive definite: itself a sign the fitted
  # parameters cannot all be identified from these data
  if (!is.null(details$ciError)) output$ci_error <- paste(as.character(details$ciError), collapse = " ")
  write_json(output, file.path(out_dir, "pi_result.json"), auto_unbox = TRUE, pretty = TRUE, digits = NA)
  progress(1)
  invisible(output)
}

if (sys.nframe() == 0L) {
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) != 2) stop("usage: run_pi.R <pi_spec.json> <output dir>")
  run_parameter_identification(args[[1]], args[[2]])
}
