// The reasons a person picks in the Data room, never types (plan 2026-11-27-one-way-in step 2; the owner's rule 2,
// 2026-11-27: "there should not be any placeholder to write the reason for the selection"). Where the record needs a why
// (another option than the suggestion, a value no file states, the send to the model), the person clicks one of these and
// the audit trail keeps it as the reason (EU GMP Annex 11 §9; 21 CFR 11.10(e) keeps who, when, before and after).

/** Why another option than the one suggested. */
export const OTHER_OPTION_REASONS = [
  "The files say otherwise",
  "Agreed with the client",
  "Better suited to the question",
  "The suggestion's evidence does not hold",
] as const;

/** Where a value no delivered file states comes from. */
export const ENTERED_REASONS = [
  "A document outside the delivery (protocol, label)",
  "Agreed with the client",
  "The published literature",
  "A modelling assumption",
] as const;

/** Why the inputs are sent to the model now. */
export const SEND_REASONS = [
  "The inputs are confirmed",
  "Confirmed with the client",
  "A first model to start from",
  "Sent again after a change",
] as const;
