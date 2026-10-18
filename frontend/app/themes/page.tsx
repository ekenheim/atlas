"use client";

// The themes, one card each: what Atlas believes, how sure it is, and what is thinnest. The same
// cards as Today, in the same order, with a line of coverage.
import { CardSkeleton, ThemeCard } from "../../components/theme-card";
import { api } from "../../lib/api/client";
import { orderThemes, themeBeliefs } from "../../lib/today";
import { useApi } from "../../lib/use-api";

const loadThemes = () => api.themes();
const loadHypotheses = async () => (await api.hypotheses()).items;
const loadBeliefs = async () => (await api.beliefs({ status: "active" })).items;

export default function ThemesPage() {
  const themes = useApi("themes", loadThemes);
  const hypotheses = useApi("hypotheses", loadHypotheses);
  const beliefs = useApi("beliefs", loadBeliefs);
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
          {orderThemes(
            themes.data,
            new Set(
              beliefs.state === "ready"
                ? themes.data
                    .filter((each) => themeBeliefs(beliefs.data, each.id).length === 0)
                    .map((each) => each.id)
                : [],
            ),
          ).map((theme) => (
            <ThemeCard key={theme.id} theme={theme} hypotheses={hypotheses} beliefs={beliefs} coverage />
          ))}
        </div>
      )}
    </div>
  );
}
