"use client";

// The person, at the foot of the sidebar (the Graphite layout, design-review/DECISIONS.md D-I4 choice 3): who is signed
// in, their account page, and Sign out. Under the development sign-in it says so: no named user.

import Link from "next/link";

import { forgetReasons } from "@/components/kit/Reason";

function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("");
}

export function Account({ user }: { user?: string | null }) {
  if (!user) return (
    <div className="sn-account" data-testid="dev-sign-in">
      <span className="avatar" aria-hidden>M1</span>
      <span className="sn-account-text">
        <Link href="/account" prefetch={false} className="sn-account-name" data-testid="nav-account">Development sign-in</Link>
        <small>no named user</small>
      </span>
    </div>
  );
  return (
    <div className="sn-account">
      <span className="avatar" aria-hidden>{initials(user)}</span>
      <span className="sn-account-text" data-testid="signed-in">
        <span className="sr-only">Signed in as </span>
        <Link href="/account" prefetch={false} className="sn-account-name" data-testid="nav-account">{user}</Link>
        {/* a route handler, not a page: a full navigation; the reasons this tab kept for the person are forgotten first */}
        <a href="/auth/logout" className="sn-signout" data-testid="sign-out" onClick={forgetReasons}>Sign out</a>
      </span>
    </div>
  );
}
