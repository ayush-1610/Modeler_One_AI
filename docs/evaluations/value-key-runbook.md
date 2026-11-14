# The value key: scoring a delivery value by value (runbook)

Plan `docs/plans/2026-11-12-client-data-intake-redesign.md`, gate **G1**; contracts
`docs/plans/2026-11-12-intake-contracts.md` §8.1 and §13. Code: `modeler_project.value_key` (the key),
`modeler_project.value_score` (the scorer and its command), `modeler_project.key_compare` (two keys compared).

The key is what people read in a client's delivery, one row per value. The scorer compares it with what the pipeline
read, value by value, and reports by field, by study, by routing tag (sub-domain) and by reading method, with the time
each stage took (G7) and the coverage numbers (G2). There is no pass mark in the code: the accuracy target is set after
the baseline (G1).

Everything here runs on the server, by people, on a real delivery. The cloud sessions cannot reach the server and
never see a client file, a key or a report with values.

## 1. Who writes the key (decision 8)

- **The scientist owns the key.** A trained analyst fills it; a second analyst fills it again, independently, from the
  same files (they do not share their keys while they work); the scientist settles every disagreement and marks the
  key `adjudicated`.
- **Whoever built the pipeline does not write the key**, and does not see it.
- The key is the analysts' reading of the files, not a fact: a mismatch is a question for both sides.

## 2. Where it lives: on the server, never in the repository

A key names the client's files and holds their values. It lives on the server only, outside the repository checkout
and outside the project store (the read root), for example:

    ~/value-keys/<delivery>/key-<analyst>.xlsx         each analyst's key
    ~/value-keys/<delivery>/key-adjudicated.xlsx        the scientist's
    ~/value-keys/<delivery>/reports/                    the reports written from it

Never commit a key, a comparison or a `--with-values` report, nor paste one into a session, an issue or a chat. The
repository holds only the synthetic keys the tests build (`key_from_truth`, the made-up drug Exampleamide).

## 3. Writing the key

Get the empty template (every column formatted as text, so `001`, `0123`, `12.40` and `1:30` stay as written):

    cd ~/Modeler_One_AI
    uv run python -m modeler_project.value_score --template ~/value-keys/<delivery>/key-<analyst>.xlsx

Its **Read me** sheet repeats what follows.

- **Header** (one row): `schema` stays `value-key/2`; `delivery` (the delivery's name or date), `analyst`, `date`;
  `status` `draft` while it is filled, `verified` when the second analyst has checked their own, `adjudicated` when
  the scientist has settled the differences.
- **Key**, one row per value the files state:
  - `file`: the file's name as delivered; `where`: the sheet's name, or the page of a PDF **as the PDF viewer counts
    it (1 = the first page), not the number printed on the page** ("Page 12 of 40" printed on the 14th page is `14`).
    For a table continued over pages, write each value's own page. A range (`2-3`, `pp. 2-3`) names every page in it:
    use it for a Not data table. A Word or text file: leave it empty. `table`: its caption or your own name for it
    (for the scientist; the score does not use it).
  - The labels, as the file writes them: `study`, `arm`, `analyte`, `matrix`, `subject`, `product`, `batch`, `vessel`,
    `period`, `occasion`, `sequence`. Write the labels the file states **for that value**: a value inside a table
    takes its table's study, arm, analyte and matrix (from the title, a header or a column) and its own row's subject,
    period or vessel; a value stated once in a title or a sentence (a dose, a food state, the number of subjects)
    takes only the study and arm it is stated for. Leave a label empty when the file does not state it: never fill one
    in from elsewhere. Subjects, vessels, periods, occasions and sequences are codes: write them with their
    punctuation (`1-01` and `10-1` are two subjects). `occasion` and `sequence` are checked on the value paired with
    the row, like the attributes below.
  - The name of a study, an arm, an analyte, a product or a batch that a title or a header writes is itself a value
    (`study_id`, `treatment`, `analyte`, `product`, `batch`), once per table that names it.
  - `conditions`: what tells two runs or intervals apart, as `name=value` pairs joined by `;`, in any order, the names
    from the field list (`medium`, `ph`, `apparatus`, `rpm`, `volume_ml`, `temperature_c`, `surfactant`,
    `interval_start_h`, `interval_end_h`, `cumulative`, `component`): `medium=0.1 N HCl;ph=1.2`. A value may hold a
    `;` (`medium=phosphate buffer; pH 6.8;ph=6.8`): a pair starts only at a `;` followed by the next `name=`.
  - `field`: the ledger's vocabulary (`modeler_intake.fields`): `concentration`, `percent_dissolved`, `dose`, `n`,
    `lloq`, `food_state`, `pk.Cmax`, `excretion.amount`, a CPF id such as `phys.logp` or `bind.fu`, and so on. An
    unknown field is refused with its cell.
  - `time` and `time_unit` (`min`, `h`, `day`): the nominal time of a value that has one.
  - `value`, **as written**: a number exactly as printed (`12.40`, `12,5`, `1 234,5`), a BLQ form (`BLQ`, `<0.5`),
    an above-range form (`>1000`), a missing token (`NS`, `n/a`), or the text of a name or a choice (`fasted`,
    `immediate release`). A number with one separator and three digits after it (`1,234` or `1.234`) can be a
    thousands group or a decimal mark: the scorer settles it from the other numbers of the same file, `where` and
    `table` (one of them written with a decimal point or a decimal comma), never by guessing; when none settles it,
    the row is listed as not usable: write `1234` (or `1.234`).
  - `unit` as written.
  - `statistic` (`individual`, `arithmetic_mean`, `geometric_mean`, `median`), `spread` (the SD, SE or CV% value as
    written), `spread_kind` (`SD`, `SE`, `CV%` ...) and `n` (the n of a mean), as the file states them for that value;
    leave them empty when the file does not. They are checked on the value paired with the row (a mean with the wrong
    SD or n, an SE taken for an SD, a geometric mean for an arithmetic one, a Day 1 value for a Day 14 one) and
    counted apart; a key that leaves them empty does not score them.
  - `note` for the scientist.
- **Studies** (optional): one row per study, its other spellings in `names` (`;`-separated), and its routing tags
  (`population`, `special_population`, `route`, `food_state`, `application`, or another tag as a new column): the
  score is then totalled per tag value, which is the sub-domain view of G1.
- **Not data** (optional): a table that holds no data (a template's instructions, a list of abbreviations), with the
  reason. Values the pipeline reads there count as unexpected.

The loader refuses a key whose shape it cannot read (a cell that is not text, a sheet, column, field or condition it
does not know, another schema, a status it does not know) and names the sheet and cell. A row it can read but not use
(an empty value, a value that is no form of a number such as `12.3 (4.5)`, a time with no known unit) is **listed in the
report, never dropped**: check that list first.

## 4. Scoring

On the server, in `~/Modeler_One_AI`, against the read root (`--tenant` only when the project id is in several):

    uv run python -m modeler_project.value_score --root ~/modeler-data/read-root --project <id> \
        --key ~/value-keys/<delivery>/key-adjudicated.xlsx --source <ledger|stores> \
        --out ~/value-keys/<delivery>/reports/<source>.md

The command reads only; it refuses to write anything inside the root. It first checks the hash chains of the intake
logs (files, runs, mappings, facts, entities, review): a broken chain means the data was changed after it was written,
and the command scores nothing unless `--accept-broken-chain` is given, in which case the break is at the top of the
report. `--json` prints the same as JSON; `--tolerance` and `--digitized-tolerance` (relative, off by default) let a
number within that share of the key's count as found (the report counts those apart); keep them off for the baseline.

**The baseline and the new pipeline on the same project.** With `MODELER_INTAKE_PIPELINE=both` (the default), one
upload is read by today's readers and by the new pipeline. Upload the whole delivery once (a new project, **+ Add
data**), wait until both are done (the reading tray empty; the pipeline's runs done), then score twice:

1. `--source stores`: **the baseline**, today's pipeline: client datasets not rejected (their points, reported PK
   parameters and study-record facts), the points of sheets read and waiting for a person, the dissolution rows and
   records, and the files' study facts. Today's stores keep no arm (it is folded into the study id: for this source
   only, the scorer also matches the key's study and arm against the id `study + arm`) and no anchor per value.
   Today's stores also keep labels another way than the key's convention: a study-record fact (a dose, n, a food
   state) has no analyte, matrix, product or batch, and a reported PK parameter carries its dataset's analyte and
   matrix. The join is exact on every label (contracts §13), so these rows are `missing` and their values
   `unexpected`. The report counts them apart as **missing rows read under other labels** (a diagnostic: same study,
   subject, field, time and value, a label stated on one side only). Read the baseline's omissions with that count
   beside them, and its concentrations knowing that the template's datasets keep actual times, not nominal ones.
2. `--source ledger`: **the new pipeline**, the ledger's active values (a derived SD is not a value of its own and is
   not scored).

**What lands.** After the scientist's Delivery confirmations, the landing writes datasets from the ledger: units are
converted for the model, the LLOQ is kept per dataset and spreads become the dataset's errors. Run `--source stores`
a third time: that score is what the model receives. A value found in the ledger and wrong after the landing is a
landing problem, not a reading one.

**What the verdicts mean.** Key rows and values are joined on what the value is about (study, arm, analyte, matrix,
subject, product, batch, vessel, period, conditions, field, time in minutes; a study also under its Studies names),
**never on where the pipeline says it found it**. Inside one join group equal values pair first, so a value stated
twice (a dose in a caption and in a synopsis) is found twice.

| verdict | means |
|---|---|
| `found` | the same value, in the same unit (12.40 and 12.4 are the same number); also a missing token (`NS`) with nothing read, counted apart |
| `found_rounded` | a workbook number cell stores more digits than it shows (12.4037 under a `0.00` format, written 12.40 in the key): the same once rounded to the key's decimals, a tie either half-even or away from zero as a spreadsheet shows it (12.25 under `0.0` is 12.3). Counted apart (decision R, contracts §11.30); PDF, Word and text values stay exact |
| `wrong_value` | another value in the key row's place: a misread, a swapped subject, a wrong row |
| `wrong_unit` | the key's value in another unit (nothing is converted) |
| `missing` | the key has it, the pipeline did not read it (an omission, counted apart from errors) |
| `unexpected` | read in a file, sheet or page the key covers, and the key does not have it |

A value read where the key covers nothing is outside the key: counted, not judged. Two kinds of value only restate
what the ledger links or what another value holds, and are never unexpected (they are scored when a key row names
them): the ledger's own cross-file links (`link.*` facts), and an `lloq` fact at a `<0.5` cell with that cell's LLOQ
(the key's `<0.5` row already checks it; an `lloq` fact there with another number is judged like any value).

Two more counts change no verdict: **attributes that differ** (a paired row whose statistic, spread, spread kind, n,
occasion or sequence, as the key states them, the value does not have), and **key places where no value was read**
(a sheet or page of the key where nothing of that file was read, while other places of the file were: a misspelt
sheet, a page not read, or a printed page number written instead of the page's position).

## 5. Two analysts: comparison and adjudication

When both analysts' keys are `verified`:

    uv run python -m modeler_project.value_score --key ~/value-keys/<delivery>/key-A.xlsx \
        --compare ~/value-keys/<delivery>/key-B.xlsx --out ~/value-keys/<delivery>/reports/comparison.md

It lists, with both row numbers, the rows only in A, only in B, with another value, in another unit, in another place
(file, sheet or page, table; `p. 2` and `2` are one page), with another attribute (statistic, spread, n ...), the Not
data tables one key lists alone, and the studies whose Studies rows differ (other names, a routing tag, or a study one
key lists alone: the tags drive the totals by tag). Rows join as the scorer joins them. The
scientist decides each, writes the decisions into a copy (`key-adjudicated.xlsx`, status `adjudicated`, the decision in
`note`) and compares that copy with each analyst's key again until nothing is left unexplained. The comparison holds
values: it stays on the server.

## 6. What to send back

To the next session (paste the text), and only this:

- **the default report** of each source (`stores`, `ledger`, and the landed `stores` when there is one). It holds
  counts, field names, verdicts, reading methods and anchors only: a study is named by the number of the first key row
  naming it, a routing tag's value only when it is a word of the field's own vocabulary (healthy, oral, fed ...), a
  sheet's name inside an anchor by its number in the report (`s:#2!C4`: the second sheet of that file the report
  names; a sheet is often named after a study), and a value's id only when it is the ledger's (`tx-...#3`, `f-41`;
  today's stores build theirs from sheet and series names, so those are numbered: `value 7`). The `--json` form holds
  the same, and its coverage drops each file's name and free-text reason. It holds no value, no label, no file name
  and no analyst. Read it before sending all the same.
- **the usage report** of the same days:

      uv run python -m modeler_agents.usage_report --root ~/modeler-data/read-root --since <the upload's date>

Never send the key, the comparison, a `--with-values` report or `--json --with-values`: they hold the client's values
and labels. `--with-values` is for the scientist on the server, to see each wrong value beside the key's.
