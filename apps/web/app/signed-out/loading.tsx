// Drawn without the app's shell (proxy.ts): no skeleton of the app's pages (its breadcrumbs read the API, which a person
// who is not signed in cannot), just the calm canvas until the page arrives.
export default function Loading() {
  return <main className="auth-page" aria-busy="true" />;
}
