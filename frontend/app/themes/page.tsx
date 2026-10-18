"use client";

// The themes, one card each: what Atlas believes, how sure it is, and what is thinnest. The same
// cards as Today, in the same order, with a line of coverage. A theme the Watch is on but nothing
// is believed of yet reads `Watching`, one it has not reached `Not started`, and a watched theme
// that is not one of the themes still gets its card (spec §10.3.1).
import { CardSkeleton, ThemeCard, WatchCard } from "../../components/theme-card";
import { api } from "../../lib/api/client";
import { orderThemes, themeBeliefs } from "../../lib/today";
import { useApi } from "../../lib/use-api";
import { themesCards } from "../../lib/watch";

const loadThemes = () => api.themes();
const loadHypotheses = async () => (await api.hypotheses()).items;
const loadBeliefs = async () => (await api.beliefs({ status: "active" })).items;
const loadBoard = async () => (await api.chokepoints({ limit: 500 })).items;
const loadRuns = async () => (await api.watchRuns({ limit: 200 })).items;

export default function ThemesPage() {
  const themes = useApi("themes", loadThemes);
  const hypotheses = useApi("hypotheses", loadHypotheses);
  const beliefs = useApi("beliefs", loadBeliefs);
  // The Watch's reads cost the page nothing when they fail or are empty (the shipping state).
  const board = useApi("board", loadBoard);
  const runs = useApi("watch-runs", loadRuns);
  return (
    <div className="themes-page">
      <h1>Themes</h1>
      {themes.state === "loading" ? (
        <div className="cards" aria-busy="true">
          <CardSkeleton label="Loading themes" />
        </div>
      ) : themes.state === "error" ? (
        <p role="alert">Could not load the themes.</p>
      ) : themes.data.length === 0 ? (
        <p className="muted">No theme yet.</p>
      ) : (
        <div className="cards">
          {themesCards(
            orderThemes(
              themes.data,
              new Set(
                beliefs.state === "ready"
                  ? themes.data
                      .filter((each) => themeBeliefs(beliefs.data, each.id).length === 0)
                      .map((each) => each.id)
                  : [],
              ),
            ),
            beliefs.state === "ready" ? beliefs.data : null,
            board.state === "ready" ? board.data : [],
            runs.state === "ready" ? runs.data : [],
          ).map((card) =>
            card.theme !== null && card.watch === null ? (
              <ThemeCard key={card.slug} theme={card.theme} hypotheses={hypotheses} beliefs={beliefs} coverage />
            ) : (
              <WatchCard
                key={card.slug}
                slug={card.slug}
                title={card.title}
                watching={card.watch?.watching ?? true}
                line={card.watch?.line ?? ""}
              />
            ),
          )}
        </div>
      )}
    </div>
  );
}
