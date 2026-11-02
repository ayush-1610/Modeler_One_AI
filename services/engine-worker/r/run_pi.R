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
#   parameters       [{name, unit, min, max, start, scale (optional), group (optional), paths: [{simulation, path}]}]
#                    one PIParameters per entry; several paths = one value shared across simulations.
#                    scale: "linear" (the default) or "log": a log-scaled parameter is optimised as log(value), and its
#                    CI is taken on that scale (asymmetric, log-normal), so it needs min > 0.
#                    group: the name of an entry of `groups`; the parameter is then simulated at f x start, f being
#                    the group's factor, so the split between the members (their starts) is kept and the data
#                    estimate only f. A member's start must be positive and f x start must stay within its min/max.
#   groups           [{name, min, max, start (optional, default 1), scale (optional)}]   the bounds and start of each
#                    group's factor f (dimensionless, min > 0); "Use as Factor" in the OSP desktop
#                    (docs/plans/2026-11-02-pi-4b-relative-group.md). A spec with no group and no log scale runs on
#                    the package's own ParameterIdentification, exactly as before either existed.
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
# the CPF ids. Empty when there is no CI.
correlation_pairs <- function(cor_mat, names) {
  pairs <- list()
  if (!is.matrix(cor_mat) || nrow(cor_mat) != length(names)) return(pairs)
  for (i in seq_len(length(names) - 1)) for (j in (i + 1):length(names)) {
    if (is.finite(cor_mat[i, j])) pairs[[length(pairs) + 1]] <- list(a = names[[i]], b = names[[j]], r = cor_mat[i, j])
  }
  pairs
}

# --- Groups and log scale (PI-4 B, docs/plans/2026-11-02-pi-4b-relative-group.md) ---------------------------------
# The package (2.2.0) optimises one value per PIParameters on its linear scale. Here the optimiser moves the "free
# vector" instead: one entry per group (its factor f) and one per parameter outside any group, in the order of
# spec$parameters (a group where its first member is), each on its own scale (log(value) for a log-scaled entry). The
# free vector is expanded to one value per PIParameters before the package's own objective function sees it, so the
# residuals, weights, LLOQ handling and algorithms are exactly the package's.

group_of <- function(p) if (is.character(p$group) && length(p$group) == 1 && nzchar(p$group)) p$group else NULL

scale_of <- function(x) {
  scale <- if (is.character(x$scale) && length(x$scale) == 1) x$scale else "linear"
  if (!scale %in% c("linear", "log")) stop(sprintf("'%s': scale must be \"linear\" or \"log\", not '%s'", x$name, scale))
  scale
}

uses_free_vector <- function(spec) {
  length(spec$groups) > 0 || any(vapply(spec$parameters, function(p) scale_of(p) == "log", logical(1)))
}

# pi_parameters: the PIParameters built from spec$parameters, in the same order, bounds and start in the base unit.
free_vector <- function(spec, pi_parameters) {
  groups <- list()
  for (g in spec$groups) {
    if (!is.null(groups[[g$name]])) stop(sprintf("group '%s' is defined twice", g$name))
    groups[[g$name]] <- g
  }
  names_of <- function(xs) vapply(xs, function(x) x$name, "")
  clash <- intersect(names(groups), names_of(spec$parameters))
  if (length(clash) > 0) stop(sprintf("group and parameter share a name: %s", paste(clash, collapse = ", ")))

  entries <- list()
  entry_of <- integer(length(spec$parameters))      # parameter k -> its entry
  multiplier <- rep(1, length(spec$parameters))     # a member's start (base unit); 1 outside any group
  for (k in seq_along(spec$parameters)) {
    p <- spec$parameters[[k]]
    pi_parameter <- pi_parameters[[k]]
    g <- group_of(p)
    if (is.null(g)) {
      entries[[length(entries) + 1]] <- list(name = p$name, kind = "parameter", scale = scale_of(p),
                                             lower = pi_parameter$minValue, upper = pi_parameter$maxValue,
                                             start = pi_parameter$startValue)
      entry_of[[k]] <- length(entries)
      next
    }
    if (is.null(groups[[g]])) stop(sprintf("parameter '%s' names group '%s', which `groups` does not define", p$name, g))
    j <- match(g, names_of(entries))
    if (is.na(j)) {
      d <- groups[[g]]
      entries[[length(entries) + 1]] <- list(name = g, kind = "group", scale = scale_of(d), lower = num(d$min),
                                             upper = num(d$max), start = if (is.null(d$start)) 1 else num(d$start),
                                             members = character())
      j <- length(entries)
    }
    entries[[j]]$members <- c(entries[[j]]$members, p$name)
    entry_of[[k]] <- j
    reference <- pi_parameter$startValue
    if (!(length(reference) == 1 && is.finite(reference) && reference > 0)) {
      stop(sprintf("parameter '%s' in group '%s': its start (the value f scales) must be positive", p$name, g))
    }
    multiplier[[k]] <- reference
  }
  unused <- setdiff(names(groups), names_of(entries))
  if (length(unused) > 0) stop(sprintf("group with no parameter: %s", paste(unused, collapse = ", ")))

  for (e in entries) {
    if (!(length(e$lower) == 1 && length(e$upper) == 1 && length(e$start) == 1 &&
          e$lower <= e$start && e$start <= e$upper)) {
      stop(sprintf("'%s': the start (%s) must lie within [min, max] = [%s, %s]", e$name, format(e$start),
                   format(e$lower), format(e$upper)))
    }
    if (e$kind == "group" && e$lower <= 0) stop(sprintf("group '%s': its factor needs min > 0", e$name))
    if (e$scale == "log" && e$lower <= 0) stop(sprintf("'%s': a log scale needs min > 0", e$name))
  }
  for (k in seq_along(spec$parameters)) {
    e <- entries[[entry_of[[k]]]]
    if (e$kind != "group") next
    # the group's factor bounds times the member's start must stay within the member's own (signed) bounds
    lo <- e$lower * multiplier[[k]]
    hi <- e$upper * multiplier[[k]]
    pi_parameter <- pi_parameters[[k]]
    tol <- 1e-9 * max(abs(c(lo, hi)))
    if (lo < pi_parameter$minValue - tol || hi > pi_parameter$maxValue + tol) {
      stop(sprintf("parameter '%s': group '%s' would move it over [%g, %g], outside its bounds [%g, %g] (base unit)",
                   spec$parameters[[k]]$name, e$name, lo, hi, pi_parameter$minValue, pi_parameter$maxValue))
    }
  }

  is_log <- vapply(entries, function(e) e$scale == "log", logical(1))
  to_free <- function(v) {   # by index: log() of a linear entry's (possibly negative) bound is never taken
    v[is_log] <- log(v[is_log])
    v
  }
  from_free <- function(x) {
    x[is_log] <- exp(x[is_log])
    x
  }
  list(
    entries = entries, entry_of = entry_of, multiplier = multiplier, is_log = is_log, names = names_of(entries),
    start = to_free(vapply(entries, function(e) e$start, 0)),
    lower = to_free(vapply(entries, function(e) e$lower, 0)),
    upper = to_free(vapply(entries, function(e) e$upper, 0)),
    values = from_free,                                        # free vector -> each entry's value (f, or the parameter's)
    expand = function(x) from_free(x)[entry_of] * multiplier   # free vector -> one value per PIParameters
  )
}

# The Hessian CI on the free vector, as the package computes it (sigma^2 = SSR / (n - p), p = the free entries), read
# back per entry and per parameter. A log entry's interval is exp() of the interval on log(value): asymmetric, never
# below zero. Its CV is the log-normal one, sqrt(exp(sd_log^2) - 1), and its SD that CV times the estimate, so a
# log-normal drawn with CV = SD / estimate (S6) has exactly sd_log on the log scale.
free_vector_ci <- function(free, x, ci) {
  n <- length(x)
  value <- free$values(x)
  entry <- list(estimate = value, sd = rep(NA_real_, n), cv = rep(NA_real_, n), lowerCI = rep(NA_real_, n),
                upperCI = rep(NA_real_, n), sd_log = rep(NA_real_, n))
  has_ci <- length(ci$sd) == n
  if (has_ci) {
    entry$sd_log <- ifelse(free$is_log, ci$sd, NA_real_)
    entry$cv <- ifelse(free$is_log, sqrt(exp(ci$sd^2) - 1), ci$sd / abs(value))
    entry$sd <- ifelse(free$is_log, entry$cv * value, ci$sd)
    entry$lowerCI <- ifelse(free$is_log, exp(ci$lowerCI), ci$lowerCI)
    entry$upperCI <- ifelse(free$is_log, exp(ci$upperCI), ci$upperCI)
  }
  per_parameter <- function(v) v[free$entry_of] * free$multiplier
  details <- ci$details %||% list()
  details$free <- entry
  list(
    sd = if (has_ci) per_parameter(entry$sd) else NULL,
    cv = if (has_ci) entry$cv[free$entry_of] else NULL,
    lowerCI = if (has_ci) per_parameter(entry$lowerCI) else NULL,
    upperCI = if (has_ci) per_parameter(entry$upperCI) else NULL,
    error = ci$error, method = ci$method, elapsed = ci$elapsed, details = details
  )
}

# ParameterIdentification with the optimiser on the free vector. It overrides the package's private .runAlgorithm
# (called only from run()) and estimateCI, and uses the package's internal Optimizer, PIResult and simulation-state
# helpers, which are not exported: pinned to ospsuite.parameteridentification 2.2.0, and golden/pi_relative_group.R
# fails if they change. Only the Hessian CI (the package's default) is supported here.
PI_NAMESPACE <- asNamespace("ospsuite.parameteridentification")

TransformedParameterIdentification <- R6::R6Class(
  "TransformedParameterIdentification",
  inherit = ParameterIdentification,
  cloneable = FALSE,   # as its superclass
  private = list(
    .free = NULL,
    .freeObjective = function() {
      free <- private$.free
      function(p, ...) private$.objectiveFunction(free$expand(p), ...)
    },
    .runAlgorithm = function() {
      free <- private$.free
      optimizer <- PI_NAMESPACE$Optimizer$new(configuration = private$.configuration)
      result <- optimizer$run(par = free$start, fn = private$.freeObjective(), lower = free$lower, upper = free$upper)
      result$free <- result$par
      result$par <- free$expand(result$par)
      result$startValues <- free$expand(free$start)
      result
    }
  ),
  public = list(
    initialize = function(..., free) {
      super$initialize(...)
      private$.free <- free
    },
    estimateCI = function() {
      if (is.null(private$.lastOptimResult)) stop("estimateCI: run() first")
      if (!identical(private$.configuration$ciMethod, "hessian")) {
        stop(sprintf("groups and log scales support the Hessian CI only, not '%s'", private$.configuration$ciMethod))
      }
      saved <- PI_NAMESPACE$.storeSimulationState(private$.simulations)
      on.exit(PI_NAMESPACE$.restoreSimulationState(private$.simulations, saved), add = TRUE)
      private$.batchInitialization()
      private$.fnEvaluations <- 0
      free <- private$.free
      x <- private$.lastOptimResult$free
      optimizer <- PI_NAMESPACE$Optimizer$new(configuration = private$.configuration)
      ci <- optimizer$estimateCI(par = x, fn = private$.freeObjective(), lower = free$lower, upper = free$upper,
                                 resetFn = function() private$.fnEvaluations <- 0)
      ospsuite::clearMemory()
      PI_NAMESPACE$PIResult$new(
        optimResult = private$.lastOptimResult,
        ciResult = free_vector_ci(free, x, ci),
        costDetails = private$.bestCostSummary %||% private$.lastCostSummary,
        configuration = private$.configuration,
        piParameters = private$.piParameters
      )
    }
  )
)

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
  id_by_path <- list()   # a fitted parameter's full PK-Sim path, as the result reports it -> the CPF id (below)
  parameters <- lapply(spec$parameters, function(p) {
    objects <- lapply(p$paths, function(x) getParameter(path = x$path, container = simulations[[x$simulation]]))
    for (o in objects) id_by_path[[o$fullPath]] <<- p$name
    pi_parameter <- PIParameters$new(parameters = objects)
    to_base <- function(v) if (has_unit(p$unit)) toBaseUnit(objects[[1]], as.numeric(v), p$unit) else as.numeric(v)
    base_factor[[p$name]] <<- if (has_unit(p$unit)) toUnit(objects[[1]], 1, p$unit) else 1
    lo <- to_base(p$min); hi <- to_base(p$max)
    # Widen first, then set the start, then narrow: the setters reject a bound on the wrong side of the start.
    pi_parameter$maxValue <- max(hi, pi_parameter$maxValue)
    pi_parameter$minValue <- min(lo, pi_parameter$minValue)
    if (!is.null(p$start)) pi_parameter$startValue <- to_base(p$start)
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

  # Groups or a log scale: the optimiser moves the free vector (above). Neither: the package's own class, as before.
  free <- if (uses_free_vector(spec)) free_vector(spec, parameters) else NULL
  arguments <- list(simulations = unname(simulations), parameters = parameters, outputMappings = mappings,
                    configuration = configuration)
  task <- if (is.null(free)) {
    do.call(ParameterIdentification$new, arguments)
  } else {
    do.call(TransformedParameterIdentification$new, c(arguments, list(free = free)))
  }
  started <- proc.time()[["elapsed"]]
  result <- task$run()
  details <- result$toList()
  estimates <- result$toDataFrame()
  estimates <- estimates[!duplicated(estimates$group), ]

  # Map each estimated parameter back to the CPF id the platform fit (spec$parameters[[i]]$name), matched by
  # the PK-Sim parameter path, so the result is keyed by the CPF id (what apply_fit_estimates expects) rather
  # than the PK-Sim parameter name. The original name is kept as pksim_name.
  # The result reports each parameter's full path: its simulation's root container, then the parameter path. That is
  # "<sim>|<parameter path>" where the pkml's simulation is named by the spec's id (the platform's), and the
  # simulation's own name otherwise (e.g. OSP's Aciclovir.pkml, "Vergin 1995 IV"): both are keyed.
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
        for (k in c("estimate", "sd", "lowerCI", "upperCI", "initialValue")) row[[k]] <- as.numeric(row[[k]]) * factor
        row$base_unit <- row$unit
        row$unit <- if (has_unit(spec_p$unit)) spec_p$unit else row$unit
        if (!is.null(free)) {
          # what the engine applied, so the platform can tell a log scale or a group was honoured
          e <- free$entries[[free$entry_of[[match(cpf_id, vapply(spec$parameters, function(p) p$name, ""))]]]]
          row$scale <- e$scale
          if (e$kind == "group") row$group <- e$name
          if (e$scale == "log") row$sd_log <- details$ciDetails$free$sd_log[[match(e$name, free$names)]] %||% NA_real_
        }
      }
      row
    }),
    # correlations between the optimised entries: the fitted parameters, or a group (by its name) in place of its
    # members; a log-scaled entry's correlation is that of log(value)
    correlations = correlation_pairs(details$ciDetails$corMat,
                                     if (is.null(free)) vapply(spec$parameters, function(p) p$name, "") else free$names),
    ospsuite = as.character(packageVersion("ospsuite")),
    parameteridentification = as.character(packageVersion("ospsuite.parameteridentification"))
  )
  if (!is.null(free)) {
    # one row per group: its factor f (dimensionless; each member's estimate is f x its start) and the CI of f
    ci <- details$ciDetails$free
    started_at <- free$values(free$start)
    output$groups <- lapply(which(vapply(free$entries, function(e) e$kind == "group", logical(1))), function(j) {
      e <- free$entries[[j]]
      first <- match(j, free$entry_of)
      row <- list(name = e$name, scale = e$scale, members = as.list(e$members), initialValue = started_at[[j]],
                  factor = details$finalParameters[[first]] / free$multiplier[[first]],
                  sd = ci$sd[[j]] %||% NA_real_, cv = ci$cv[[j]] %||% NA_real_,
                  lowerCI = ci$lowerCI[[j]] %||% NA_real_, upperCI = ci$upperCI[[j]] %||% NA_real_)
      if (e$scale == "log") row$sd_log <- ci$sd_log[[j]] %||% NA_real_
      row
    })
  }
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
