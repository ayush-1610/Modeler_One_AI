// The Help page's topics (P-30, the console redesign's slice 2): how Modeler One works, in plain words. Each topic
// states what the product does today (docs/USING_THE_TOOL.md and the MS-01 ruleset's stage names); none adds a rule.

export type HelpTopic = { id: string; title: string; body: string[] };

export const HELP_TOPICS: HelpTopic[] = [
  { id: "start", title: "Getting started", body: [
    "A project starts from a client's proposal and files, on Create project.",
    "It moves through four steps: Start (the brief), Data (the Data room holds what the client sent; Inputs holds what goes into the model), Review & sign (the model analysis plan, the MAP) and Run (the campaigns).",
    "Home and Your work list what waits on you across projects; each item opens the page where it is done.",
  ] },
  { id: "words", title: "Status words", body: [
    "Missing: no file or source gives the value yet.",
    "To confirm: the client's data or a draft wait for your sign-off.",
    "To decide: a choice only a person can make.",
    "Done: nothing waits.",
  ] },
  { id: "sign", title: "Signatures", body: [
    "A signature follows 21 CFR Part 11: it comes from your identity provider's step-up, and Modeler One never asks for your password.",
    "Only a project's owner changes it. A reviewer the project is shared with may sign its plan and decide its escalations.",
  ] },
  { id: "blind", title: "Blinding", body: [
    "External-validation studies are withheld until the MAP is signed, on every page that would show them.",
  ] },
  { id: "stages", title: "MS-01 stages", body: [
    "S0 readiness · S1 IV disposition · S2 oral fasted · S3 formulation and fed · SJ joint refinement · S4 internal validation · S5 external validation · S6 prediction · S7 report and package.",
    "A stage that cannot go on (its rounds or time spent, no permitted action left) stops and asks for a signed decision: retry, accept the best so far, or stop.",
  ] },
  { id: "results", title: "Results and test runs", body: [
    "A result counts only when it ran on PK-Sim. A campaign run on the software test fixture says so on its page: its numbers check the software, not the pharmacology.",
  ] },
];
