#!/usr/bin/env Rscript
# Smoke test for run_pi.R on OSP's Aciclovir example: writes a platform-style PI spec from the example
# data shipped with ospsuite.parameteridentification, runs it, and checks the result file.
#
#   Rscript pi_smoke.R <work dir>

suppressPackageStartupMessages({
  library(ospsuite)
  library(ospsuite.parameteridentification)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
work <- if (length(args) >= 1) args[[1]] else tempfile("pi_smoke_")
dir.create(work, recursive = TRUE, showWarnings = FALSE)
script_dir <- dirname(normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE))))

pkml <- system.file("extdata", "Aciclovir.pkml", package = "ospsuite")
observed_file <- system.file("extdata", "Aciclovir_Profiles.xlsx", package = "ospsuite.parameteridentification")
importer <- createImporterConfigurationForFile(filePath = observed_file)
importer$namingPattern <- "{Source}.{Sheet}.{Dose}"
observed <- loadDataSetsFromExcel(xlsFilePath = observed_file, importerConfigurationOrPath = importer)
dataset <- observed[[grep("250", names(observed), fixed = TRUE)[[1]]]]
frame <- dataSetToDataFrame(dataset)

spec <- list(
  start_index = 0,
  seed = 1,
  algorithm = "BOBYQA",
  max_evaluations = 200,
  simulations = list(list(id = "IV250", pkml = pkml)),
  parameters = list(
    list(name = "Lipophilicity", unit = "Log Units", min = -10, max = 10, start = 0,
         paths = list(list(simulation = "IV250", path = "Aciclovir|Lipophilicity")))
  ),
  output_mappings = list(list(
    simulation = "IV250",
    output_path = "Organism|PeripheralVenousBlood|Aciclovir|Plasma (Peripheral Venous Blood)",
    scaling = "log",
    observed = list(
      name = dataset$name, time = frame$xValues, time_unit = unique(frame$xUnit)[[1]],
      values = frame$yValues, unit = unique(frame$yUnit)[[1]], sd = list(), mol_weight = 225.21
    )
  ))
)
spec_path <- file.path(work, "pi_spec.json")
write_json(spec, spec_path, auto_unbox = TRUE, pretty = TRUE, digits = NA)

# run_pi.R lives in ../r/ in the repository and next to the golden folder (/engine/run_pi.R) in the engine image.
run_pi <- Filter(file.exists, c(file.path(script_dir, "..", "r", "run_pi.R"), file.path(script_dir, "..", "run_pi.R")))
if (length(run_pi) == 0) stop("run_pi.R not found next to the golden folder")
source(run_pi[[1]])
result <- run_parameter_identification(spec_path, file.path(work, "out"))
stopifnot(file.exists(file.path(work, "out", "pi_result.json")), length(result$estimates) == 1, is.finite(result$objective_value))
cat("PI SMOKE OK:", result$estimates[[1]]$name, "=", result$estimates[[1]]$estimate, "after", result$function_evaluations, "evaluations\n")

# A weight on the dataset (the joint refinement's equal weight per study, MS-01 v1.1 SJ, D-04) multiplies each residual
# before squaring: on one dataset the optimum stays where it is and the objective scales by weight^2.
weighted <- spec
weighted$output_mappings[[1]]$observed$weight <- 2
weighted_path <- file.path(work, "pi_spec_weighted.json")
write_json(weighted, weighted_path, auto_unbox = TRUE, pretty = TRUE, digits = NA)
w_result <- run_parameter_identification(weighted_path, file.path(work, "out_weighted"))
ratio <- w_result$objective_value / result$objective_value
shift <- abs(w_result$estimates[[1]]$estimate - result$estimates[[1]]$estimate)
stopifnot(is.finite(ratio), abs(ratio - 4) < 0.1, shift < 0.05)
cat("PI SMOKE WEIGHTED OK: objective x", ratio, "(expected 4), estimate moved", shift, "\n")

# Two parameters fitted together report their correlation from the Hessian CI (run_pi.R `correlations`), or say why
# there is no CI (`ci_error`). Aciclovir's tubular secretion is fitted beside lipophilicity at the path the package's
# own tests and user guide fit (OSPSuite.ParameterIdentification v2.2.0, tests/testthat/helper-for-tests.R).
TS_PATH <- "Neighborhoods|Kidney_pls_Kidney_ur|Aciclovir|Renal Clearances-TS-Aciclovir|TSspec"
pair <- spec
pair$parameters <- c(spec$parameters, list(list(name = "TSspec", unit = "1/min", min = 0.01, max = 100, start = 0.5,
                                                paths = list(list(simulation = "IV250", path = TS_PATH)))))
pair_path <- file.path(work, "pi_spec_pair.json")
write_json(pair, pair_path, auto_unbox = TRUE, pretty = TRUE, digits = NA)
both <- run_parameter_identification(pair_path, file.path(work, "out_pair"))
stopifnot(length(both$estimates) == 2, length(both$correlations) == 1 || !is.null(both$ci_error))
if (length(both$correlations) == 1) {
  r <- both$correlations[[1]]
  stopifnot(identical(c(r$a, r$b), c("Lipophilicity", "TSspec")), abs(r$r) <= 1 + 1e-9)
  cat("PI SMOKE CORRELATION OK: r(Lipophilicity, TSspec) =", r$r, "\n")
} else {
  cat("PI SMOKE CORRELATION OK: no CI (", both$ci_error, ")\n")
}
