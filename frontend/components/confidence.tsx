// A confidence as a 56 by 4 px track with a fill, and the number beside it in tabular figures.
// The bar is plain: no ticks, and it is continuous because production holds seven values
// between 50 and 85 per cent. The bar is decoration (aria-hidden); the number is its text.
import { confidenceText } from "../lib/beliefs";

export function Confidence({ value }: { value: number }) {
  const width = Math.max(0, Math.min(1, value)) * 100;
  return (
    <span className="confidence">
      <span className="confidence-track" aria-hidden="true">
        <span className="confidence-fill" style={{ width: `${width}%` }} />
      </span>
      <span className="confidence-number">{confidenceText(value)}</span>
    </span>
  );
}
