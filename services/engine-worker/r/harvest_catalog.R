#!/usr/bin/env Rscript
# Engine catalog harvest (task T-02). Exports one machine-readable JSON describing what THIS engine
# image can build: dimensions and their units, PK parameter names, species and populations, and — read
# from real OSP library snapshots, never invented — compound process types, formulation types,
# calculation methods, expression-profile types, event/meal templates, and the exact simulation-level
# naming of process selections. The Python builder catalog (pbpk_domain.catalog) loads this file; T-03's
# CPF binding refuses to emit anything that is not present here.
#
#   LC_ALL=en_US.UTF-8 Rscript harvest_catalog.R <catalog.json> <reference snapshot dir>
#
# Every discovery is wrapped: whatever this engine version does not expose is listed under "unresolved"
# rather than guessed or aborting the harvest. The reference dir is populated by fetch_reference_snapshots.sh.

suppressPackageStartupMessages({
  library(ospsuite)
  library(jsonlite)
  library(digest)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) stop("usage: harvest_catalog.R <catalog.json> [reference snapshot dir]")
out_path <- args[[1]]
reference_dir <- if (length(args) >= 2) args[[2]] else ""
dir.create(dirname(normalizePath(out_path, mustWork = FALSE)), recursive = TRUE, showWarnings = FALSE)
work <- tempfile("harvest_")
dir.create(work, recursive = TRUE)

unresolved <- character(0)
note_unresolved <- function(what, why) {
  unresolved[[length(unresolved) + 1]] <<- sprintf("%s: %s", what, why)
  cat(sprintf("  unresolved  %-28s %s\n", what, why))
}
# Run expr; on any error record it under `label` in unresolved and return `default` instead of aborting.
try_get <- function(label, expr, default = NULL) {
  tryCatch(force(expr), error = function(e) {
    note_unresolved(label, conditionMessage(e))
    default
  })
}
chr <- function(x) as.character(unlist(x, use.names = FALSE))

cat("== engine\n")
initPKSim()
engine <- list(
  ospsuite = as.character(packageVersion("ospsuite")),
  parameter_identification = try_get("PI version", as.character(packageVersion("ospsuite.parameteridentification")), NA),
  rSharp = try_get("rSharp version", as.character(packageVersion("rSharp")), NA),
  r_version = R.version.string,
  platform = R.version$platform,
  harvested_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z"),
  snapshot_version = NA  # filled from the first fixture that round-trips
)

# --- direct engine API ---------------------------------------------------------------------------
cat("== dimensions and units\n")
dimensions <- list()
dim_names <- try_get("dimensions", ospsuite::allAvailableDimensions(), character(0))
for (d in dim_names) {
  units <- try_get(sprintf("units[%s]", d), chr(ospsuite::getUnitsForDimension(d)), character(0))
  base_unit <- try_get(sprintf("baseUnit[%s]", d), ospsuite::getDimensionByName(d)$baseUnitName, NA)
  if (is.null(base_unit) || identical(base_unit, "")) base_unit <- NA  # ospsuite 12.4.4 leaves this empty
  dimensions[[length(dimensions) + 1]] <- list(name = d, base_unit = base_unit, units = as.list(units))
}
cat(sprintf("  %d dimensions\n", length(dimensions)))

cat("== PK parameters\n")
pk_parameters <- try_get("pk_parameters", chr(ospsuite::allPKParameterNames()), character(0))
cat(sprintf("  %d PK parameter names\n", length(pk_parameters)))

cat("== species and populations\n")
species <- try_get("species", chr(ospsuite::Species), character(0))
human_populations <- try_get("human_populations", chr(ospsuite::HumanPopulation), character(0))
populations <- list()
if (length(human_populations) > 0) populations[["Human"]] <- as.list(human_populations)
if (length(species) > 1) {
  note_unresolved("non_human_populations",
                  "ospsuite exposes population lists only for Human (HumanPopulation); other species' populations must be harvested from fixtures")
}

# --- fixture harvest -----------------------------------------------------------------------------
# Read process/formulation/calc-method/expression/event names straight from real snapshots, then load
# each through the engine to prove it is a snapshot this image accepts and to capture its Version.
first_present <- function(lst, keys) {
  for (k in keys) if (!is.null(lst[[k]])) return(lst[[k]])
  NULL
}
param_specs <- function(params) {
  # params: a snapshot Parameters array; return list(name, unit) preserving order, unit NULL -> dimensionless
  lapply(params %||% list(), function(p) list(name = p$Name %||% p$Path %||% "", unit = p$Unit %||% NA))
}

process_types <- list()      # keyed by internal_name
formulation_types <- list()  # keyed by formulation type
calc_compound <- character(0)
calc_individual <- character(0)
expression_types <- list()   # keyed by profile Type
event_templates <- list()    # keyed by template name
selection_naming <- list()   # observations of process-selection names
fixtures <- list()

record_process_type <- function(internal_name, kind, params, source) {
  if (is.null(internal_name) || internal_name == "") return(invisible())
  entry <- process_types[[internal_name]] %||% list(internal_name = internal_name, kind = kind,
                                                     parameters = param_specs(params), seen_in = character(0))
  entry$seen_in <- union(entry$seen_in, source)
  if (length(entry$parameters) == 0) entry$parameters <- param_specs(params)
  process_types[[internal_name]] <<- entry
}

reference_files <- character(0)
if (nzchar(reference_dir) && dir.exists(reference_dir)) {
  reference_files <- list.files(reference_dir, pattern = "\\.json$", full.names = TRUE)
}
# Always include the platform's own example snapshot if present next to this script.
script_dir <- dirname(normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE))))
example <- Filter(file.exists, c(file.path(script_dir, "golden", "example_snapshot.json"),
                                 file.path(script_dir, "..", "golden", "example_snapshot.json")))
reference_files <- unique(c(reference_files, example))
if (length(reference_files) == 0) note_unresolved("reference_snapshots", "no reference snapshots given; process/formulation/calc-method naming not harvested")

cat("== fixtures\n")
for (path in reference_files) {
  name <- tools::file_path_sans_ext(basename(path))
  snap <- try_get(sprintf("parse[%s]", name), fromJSON(path, simplifyVector = FALSE))
  if (is.null(snap)) next
  fx <- list(name = name, file = basename(path), sha256 = digest(file = path, algo = "sha256"),
             version = snap$Version %||% NA, roundtrip_ok = FALSE)
  if (is.na(engine$snapshot_version) && !is.null(snap$Version)) engine$snapshot_version <- snap$Version

  # In real snapshots a compound process has no Name: it is identified by InternalName + Molecule +
  # DataSource. The selection Name is assigned at the simulation level. A molecule can appear in several
  # processes (e.g. a perpetrator both inhibits and induces CYP3A4), each with its own data source, so
  # collect ALL of a molecule's data sources here and match the selection name against the set below.
  molecule_sources <- list()
  for (comp in snap$Compounds %||% list()) {
    calc_compound <- union(calc_compound, chr(comp$CalculationMethods))
    for (proc in comp$Processes %||% list()) {
      record_process_type(proc$InternalName, first_present(proc, c("ProcessType", "Kind")), proc$Parameters, name)
      if (!is.null(proc$Molecule)) {
        m <- proc$Molecule
        molecule_sources[[m]] <- unique(c(molecule_sources[[m]], proc$DataSource %||% ""))
      }
    }
  }
  # Simulation-level process selection naming (Simulations[].Compounds[].Processes[]): molecule-based
  # selections are "{MoleculeName}-{DataSource}"; systemic ones carry SystemicProcessType (e.g. GFR) and
  # are "Glomerular Filtration-{DataSource}". A selection is confirmed when its Name equals
  # "{molecule}-{ds}" for one of that molecule's data sources. Deduplicated per fixture because the same
  # selection repeats across every simulation in a snapshot.
  seen_selection <- character(0)
  for (sim in snap$Simulations %||% list()) {
    for (sc in sim$Compounds %||% list()) {
      for (sel in sc$Processes %||% list()) {
        sel_name <- sel$Name %||% NA
        key <- paste(name, sel_name %||% "<none>", sel$MoleculeName %||% "-", sep = "")
        if (key %in% seen_selection) next
        seen_selection <- c(seen_selection, key)
        mol <- sel$MoleculeName %||% NA
        candidates <- if (!is.na(mol) && !is.null(molecule_sources[[mol]])) molecule_sources[[mol]] else character(0)
        matched_ds <- NA
        if (!is.na(sel_name) && length(candidates) > 0) {
          hits <- candidates[vapply(candidates, function(ds) identical(sel_name, paste0(mol, "-", ds)), logical(1))]
          if (length(hits) > 0) matched_ds <- hits[[1]]
        }
        selection_naming[[length(selection_naming) + 1]] <- list(
          internal_name = NA, name = sel_name, molecule = mol, data_source = matched_ds,
          systemic_process_type = sel$SystemicProcessType %||% NA,
          matches_molecule_dash_source = !is.na(matched_ds), seen_in = name
        )
      }
    }
  }
  for (form in snap$Formulations %||% list()) {
    ftype <- first_present(form, c("FormulationType", "Type"))
    if (!is.null(ftype)) {
      entry <- formulation_types[[ftype]] %||% list(internal_name = ftype, parameters = param_specs(form$Parameters), seen_in = character(0))
      entry$seen_in <- union(entry$seen_in, name)
      if (length(entry$parameters) == 0) entry$parameters <- param_specs(form$Parameters)
      formulation_types[[ftype]] <- entry
    }
  }
  for (ind in snap$Individuals %||% list()) {
    calc_individual <- union(calc_individual, chr(first_present(ind$OriginData %||% ind, c("CalculationMethods"))))
  }
  for (prof in snap$ExpressionProfiles %||% list()) {
    ptype <- prof$Type %||% "Unknown"
    entry <- expression_types[[ptype]] %||% list(type = ptype, fields = character(0), seen_in = character(0))
    entry$fields <- union(entry$fields, names(prof))
    entry$seen_in <- union(entry$seen_in, name)
    expression_types[[ptype]] <- entry
  }
  for (ev in snap$Events %||% list()) {
    tmpl <- first_present(ev, c("Template", "TemplateName", "Name"))
    if (!is.null(tmpl)) {
      entry <- event_templates[[tmpl]] %||% list(name = tmpl, seen_in = character(0))
      entry$seen_in <- union(entry$seen_in, name)
      event_templates[[tmpl]] <- entry
    }
  }

  # Prove the engine accepts this snapshot (also confirms the fixtures are usable in golden tests).
  # ospsuite 12.4.4 segfaults in loadProjectFromSnapshot on macOS, so that verification runs on Linux only;
  # everything above (metadata, names, units) is read from JSON and works anywhere.
  if (identical(Sys.info()[["sysname"]], "Darwin")) {
    fx$roundtrip_ok <- NA
    load_label <- "SKIP(macOS)"
  } else {
    proj_dir <- file.path(work, name)
    ok <- tryCatch({
      dir.create(proj_dir, showWarnings = FALSE)
      loadProjectFromSnapshot(normalizePath(path), output = proj_dir, runSimulations = FALSE)
      TRUE
    }, error = function(e) { note_unresolved(sprintf("load[%s]", name), conditionMessage(e)); FALSE })
    fx$roundtrip_ok <- isTRUE(ok)
    load_label <- if (fx$roundtrip_ok) "OK" else "FAIL"
  }
  fixtures[[length(fixtures) + 1]] <- fx
  cat(sprintf("  %-22s version=%s load=%s procs=%d forms=%d\n", name, fx$version,
              load_label, length(comp$Processes %||% list()), length(snap$Formulations %||% list())))
}

# --- assemble ------------------------------------------------------------------------------------
# Force list-valued fields to JSON arrays: write_json(auto_unbox = TRUE) unboxes a length-1 atomic
# vector to a scalar, which would turn a single-element seen_in into a bare string. as.list() keeps arrays.
listify <- function(entries, cols) {
  lapply(entries, function(e) {
    for (col in cols) if (!is.null(e[[col]])) e[[col]] <- as.list(e[[col]])
    e
  })
}
process_types <- listify(process_types, "seen_in")
formulation_types <- listify(formulation_types, "seen_in")
expression_types <- listify(expression_types, c("seen_in", "fields"))
event_templates <- listify(event_templates, "seen_in")
unname_entries <- function(x) unname(x)
catalog <- list(
  engine = engine,
  dimensions = dimensions,
  pk_parameters = as.list(pk_parameters),
  species = as.list(species),
  populations = populations,
  process_types = unname_entries(process_types),
  formulation_types = unname_entries(formulation_types),
  calculation_methods = list(compound = as.list(calc_compound), individual = as.list(calc_individual)),
  expression_types = unname_entries(expression_types),
  event_templates = unname_entries(event_templates),
  process_selection_naming = selection_naming,
  fixtures = fixtures,
  unresolved = as.list(unresolved)
)

write_json(catalog, out_path, auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null", digits = NA)
cat(sprintf("\nWrote %s\n", out_path))
cat(sprintf("  dimensions=%d pk_parameters=%d species=%d process_types=%d formulation_types=%d fixtures=%d unresolved=%d\n",
            length(dimensions), length(pk_parameters), length(species), length(process_types),
            length(formulation_types), length(fixtures), length(unresolved)))
unlink(work, recursive = TRUE)
