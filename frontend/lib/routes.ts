// Pages take their id as a query parameter, so the static export needs no dynamic routes.
const withId = (page: string) => (id: string) => `/${page}/?id=${encodeURIComponent(id)}`;

export const routes = {
  companies: "/",
  company: withId("company"),
  source: withId("source"),
  version: withId("version"),
};
