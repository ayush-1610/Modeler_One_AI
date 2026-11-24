"use client";

// Review & sign read by a member who may not change the plan (a viewer, QA: the API's `plan:view`, R-S03): every part
// of the page shows what the plan says and offers no control that would only be refused (the console redesign's
// slice 5). The page sets it once from the API's word on the person's roles; each part asks it.

import { createContext, useContext } from "react";

export const PlanReadOnly = createContext(false);

/** Whether the plan is read only here: its controls are not offered. */
export const useReadOnly = () => useContext(PlanReadOnly);
