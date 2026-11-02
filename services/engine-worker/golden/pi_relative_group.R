#!/usr/bin/env Rscript
# Golden case for groups and log scales in run_pi.R (PI-4 B1, docs/plans/2026-11-02-pi-4b-relative-group.md), with
# known truth on OSP's Aciclovir example. Its kidney has two parallel elimination processes (ospsuite 12.4.4's
# Aciclovir.pkml, Neighborhoods|Kidney_pls_Kidney_ur|Aciclovir): glomerular filtration ("GFR fraction") and
# first-order tubular secretion ("TSspec", the parameter pi_smoke.R fits); its hepatic clearance is 0. A plasma
# profile is simulated with a known factor on the model's own values, then fitted:
#   A  both processes as one group, linear     the factor comes back, each member is f x its start (the split is
#                                              kept), and the factor has a CI
#   B  the same group, log scale               the same factor; its CI is symmetric on the log scale and above zero
#   C  secretion alone, log scale              (a profile with secretion alone scaled) the value comes back; log CI
#   D  secretion alone, a spec as before       the package's own class: no scale or group in the result
#   E  secretion alone, scale "linear"         exactly D
#   F  lipophilicity beside the group (log)    the correlations name the group in place of its members
#
#   Rscript pi_relative_group.R <work dir>

suppressPackageStartupMessages({
  library(ospsuite)
  library(ospsuite.parameteridentification)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
work <- if (length(args) >= 1) args[[1]] else tempfile("pi_relative_group_")
dir.create(work, recursive = TRUE, showWarnings = FALSE)
script_dir <- dirname(normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE))))

# run_pi.R lives in ../r/ in the repository and next to the golden folder (/engine/run_pi.R) in the engine image.
run_pi <- Filter(file.exists, c(file.path(script_dir, "..", "r", "run_pi.R"), file.path(script_dir, "..", "run_pi.R")))
if (length(run_pi) == 0) stop("run_pi.R not found next to the golden folder")
source(run_pi[[1]])

pkml <- system.file("extdata", "Aciclovir.pkml", package = "ospsuite")
GFR_PATH <- "Neighborhoods|Kidney_pls_Kidney_ur|Aciclovir|Glomerular Filtration-GFR-Aciclovir|GFR fraction"
TS_PATH <- "Neighborhoods|Kidney_pls_Kidney_ur|Aciclovir|Renal Clearances-TS-Aciclovir|TSspec"
LIPO_PATH <- "Aciclovir|Lipophilicity"
OUTPUT <- "Organism|PeripheralVenousBlood|Aciclovir|Plasma (Peripheral Venous Blood)"
TRUTH <- 0.5   # the known factor; it keeps the GFR fraction at or below 1

# The model's own values, in the base unit (the specs below give every value in the base unit, so they carry no unit).
model <- loadSimulation(pkml, loadFromCache = FALSE)
gfr0 <- getParameter(GFR_PATH, model)$value
ts0 <- getParameter(TS_PATH, model)$value
lipo0 <- getParameter(LIPO_PATH, model)$value
stopifnot(is.finite(gfr0), gfr0 > 0, is.finite(ts0), ts0 > 0, is.finite(lipo0))
cat(sprintf("Aciclovir: GFR fraction %g, TSspec %g %s, lipophilicity %g\n", gfr0, ts0,
            getParameter(TS_PATH, model)$unit, lipo0))

# The plasma profile with the two renal processes at the given values, 16 points over the simulated time, in the
# output's base unit. A fixed +-4 % pattern gives the Hessian CI a residual variance to work with; on the log scale its
# mean is -0.08 %, so it moves the optimum by far less than the tolerances below.
profile <- function(gfr, ts) {
  sim <- loadSimulation(pkml, loadFromCache = FALSE)
  setParameterValues(list(getParameter(GFR_PATH, sim), getParameter(TS_PATH, sim)), c(gfr, ts))
  clearOutputs(sim)
  addOutputs(OUTPUT, sim)
  data <- getOutputValues(runSimulations(sim)[[1]], quantitiesOrPaths = OUTPUT)$data
  keep <- which(data$Time > 0 & data[[OUTPUT]] > 0)
  pick <- keep[unique(round(seq(1, length(keep), length.out = 16)))]
  quantity <- getQuantity(OUTPUT, sim)
  list(name = sprintf("truth GFR %g TS %g", gfr, ts), time = data$Time[pick], time_unit = getBaseUnit(ospDimensions$Time),
       values = data[[OUTPUT]][pick] * (1 + 0.04 * rep_len(c(1, -1), length(pick))), unit = quantity$unit,
       dimension = quantity$dimension, sd = list(), mol_weight = 225.21)
}

parameter <- function(name, path, start, min, max, group = NULL, scale = NULL) {
  p <- list(name = name, min = min, max = max, start = start, paths = list(list(simulation = "IV250", path = path)))
  if (!is.null(group)) p$group <- group
  if (!is.null(scale)) p$scale <- scale
  p
}

spec_for <- function(parameters, observed, groups = NULL) {
  spec <- list(
    start_index = 0, seed = 1, algorithm = "BOBYQA", max_evaluations = 200,
    simulations = list(list(id = "IV250", pkml = pkml)),
    parameters = parameters,
    output_mappings = list(list(simulation = "IV250", output_path = OUTPUT, scaling = "log", observed = observed))
  )
  if (!is.null(groups)) spec$groups <- groups
  spec
}

fit <- function(label, spec) {
  path <- file.path(work, paste0("pi_spec_", label, ".json"))
  write_json(spec, path, auto_unbox = TRUE, pretty = TRUE, digits = NA)
  out <- file.path(work, paste0("out_", label))
  result <- run_parameter_identification(path, out)
  stopifnot(file.exists(file.path(out, "pi_result.json")), is.finite(result$objective_value))
  result
}

estimate_of <- function(result, name) {
  hit <- Filter(function(e) identical(e$name, name), result$estimates)
  stopifnot(length(hit) == 1)
  hit[[1]]
}

close_to <- function(x, target, tol) is.finite(x) && abs(x / target - 1) < tol

log_symmetric <- function(x) {
  is.finite(x$lowerCI) && x$lowerCI > 0 && abs(log(x$upperCI) + log(x$lowerCI) - 2 * log(x[[if (is.null(x$factor)) "estimate" else "factor"]])) < 1e-6
}

renal <- profile(gfr0 * TRUTH, ts0 * TRUTH)
members <- function() list(
  parameter("GFR_fraction", GFR_PATH, gfr0, gfr0 / 100, gfr0 * 10, group = "renal"),
  parameter("TSspec", TS_PATH, ts0, ts0 / 100, ts0 * 10, group = "renal")
)
renal_group <- function(scale) list(list(name = "renal", min = 0.1, max = 1, start = 0.9, scale = scale))

check_group <- function(result, scale) {
  stopifnot(length(result$groups) == 1, length(result$estimates) >= 2)
  g <- result$groups[[1]]
  stopifnot(identical(g$name, "renal"), identical(g$scale, scale),
            identical(unlist(g$members), c("GFR_fraction", "TSspec")))
  gfr <- estimate_of(result, "GFR_fraction")
  ts <- estimate_of(result, "TSspec")
  stopifnot(close_to(g$factor, TRUTH, 0.03))                                 # the factor comes back
  stopifnot(close_to(gfr$estimate, g$factor * gfr0, 1e-9), close_to(ts$estimate, g$factor * ts0, 1e-9))  # split kept
  stopifnot(identical(gfr$group, "renal"), identical(ts$group, "renal"), identical(gfr$scale, scale),
            identical(ts$scale, scale))
  stopifnot(is.finite(g$sd), g$sd > 0, g$lowerCI < g$factor, g$factor < g$upperCI)  # the factor has a CI
  stopifnot(close_to(ts$lowerCI, g$lowerCI * ts0, 1e-9), close_to(ts$upperCI, g$upperCI * ts0, 1e-9))
  g
}

# A: the group, linear
a <- check_group(fit("group_linear", spec_for(members(), renal, renal_group("linear"))), "linear")
stopifnot(abs((a$upperCI - a$factor) - (a$factor - a$lowerCI)) < 1e-9 * a$factor)   # a linear CI is symmetric
cat(sprintf("PI GROUP LINEAR OK: factor %.4f (truth %g), 95 %% CI [%.4f, %.4f]\n", a$factor, TRUTH, a$lowerCI, a$upperCI))

# B: the group, log scale
b <- check_group(fit("group_log", spec_for(members(), renal, renal_group("log"))), "log")
stopifnot(log_symmetric(b), is.finite(b$sd_log), b$sd_log > 0,
          abs(b$cv - sqrt(exp(b$sd_log^2) - 1)) < 1e-12, close_to(b$sd, b$cv * b$factor, 1e-9),
          close_to(b$factor, a$factor, 0.01))                                 # the same minimum as A
cat(sprintf("PI GROUP LOG OK: factor %.4f, 95 %% CI [%.4f, %.4f], sd(log) %.4f\n", b$factor, b$lowerCI, b$upperCI, b$sd_log))

# C, D, E: tubular secretion alone, from a profile with secretion alone scaled
secretion <- profile(gfr0, ts0 * TRUTH)
alone <- function(scale) spec_for(list(parameter("TSspec", TS_PATH, ts0, ts0 / 100, ts0 * 10, scale = scale)), secretion)

c_log <- fit("secretion_log", alone("log"))
c_ts <- estimate_of(c_log, "TSspec")
stopifnot(length(c_log$groups) == 0, is.null(c_ts$group), identical(c_ts$scale, "log"),
          close_to(c_ts$estimate, ts0 * TRUTH, 0.03), log_symmetric(c_ts), is.finite(c_ts$sd_log))
cat(sprintf("PI LOG OK: TSspec %.5g (truth %.5g), 95 %% CI [%.5g, %.5g]\n", c_ts$estimate, ts0 * TRUTH, c_ts$lowerCI, c_ts$upperCI))

d_before <- fit("secretion_as_before", alone(NULL))
d_ts <- estimate_of(d_before, "TSspec")
stopifnot(is.null(d_before$groups), is.null(d_ts$scale), is.null(d_ts$group), is.null(d_ts$sd_log),
          close_to(d_ts$estimate, ts0 * TRUTH, 0.03), close_to(d_ts$estimate, c_ts$estimate, 0.01))
e_linear <- fit("secretion_linear", alone("linear"))
e_ts <- estimate_of(e_linear, "TSspec")
stopifnot(is.null(e_linear$groups), is.null(e_ts$scale),
          isTRUE(all.equal(e_ts$estimate, d_ts$estimate, tolerance = 1e-10)),
          isTRUE(all.equal(e_linear$objective_value, d_before$objective_value, tolerance = 1e-10)))
cat(sprintf("PI AS BEFORE OK: TSspec %.5g on the package's own class, unchanged with scale \"linear\"\n", d_ts$estimate))

# F: lipophilicity beside the group: the correlations name the optimised entries, the group in place of its members
f_both <- fit("group_and_lipophilicity", spec_for(
  c(list(parameter("Lipophilicity", LIPO_PATH, lipo0, lipo0 - 2, lipo0 + 2)), members()), renal, renal_group("log")))
f_group <- f_both$groups[[1]]
stopifnot(length(f_both$estimates) == 3, length(f_both$groups) == 1, close_to(f_group$factor, TRUTH, 0.05),
          identical(estimate_of(f_both, "Lipophilicity")$scale, "linear"), is.null(estimate_of(f_both, "Lipophilicity")$group))
if (is.null(f_both$ci_error)) {
  stopifnot(length(f_both$correlations) == 1)
  r <- f_both$correlations[[1]]
  stopifnot(identical(c(r$a, r$b), c("Lipophilicity", "renal")), abs(r$r) <= 1 + 1e-9)
  cat(sprintf("PI GROUP CORRELATION OK: r(Lipophilicity, renal) = %.3f, factor %.4f\n", r$r, f_group$factor))
} else {
  stopifnot(length(f_both$correlations) == 0)
  cat("PI GROUP CORRELATION OK: no CI (", f_both$ci_error, "), factor", f_group$factor, "\n")
}
cat("PI RELATIVE GROUP OK\n")
