# Chokepoint bake-off: robotics, as of 2026-10-19

You are one side of a blind comparison. Another research system is answering the same brief, and
a judge will compare the two outputs with the system names removed. Use the
`serenity-aleabitoreddit` skill as your analytical lens. **Do not run its step 0 (the self-update):
use the copy on disk as it is.** Write the skill's commit hash at the top of your answer.

## The task

Find supply-chain chokepoints in **robotics manufacturing**, as of **2026-10-19**.

- **Demand driver:** factory automation and humanoid-robot programmes at automakers, electronics
  makers and logistics operators, and the robot makers scaling production to serve them.
- **A chokepoint** is an input, a process step or a capacity that cannot meet demand over the
  relevant horizon, because no qualified second source or substitute exists. Whoever controls it
  may gain pricing power.
- **Scope:** industrial, collaborative and humanoid robots and the supply chain beneath them:
  actuators, precision reducers (strain-wave, cycloidal, planetary, roller and ball screws),
  motors and drives, sensors, controllers and robot compute, rare-earth magnets and their
  feedstock, and the machine tools and test equipment that gate production.
- **Budget:** about 60 tool calls. Name **at most 3 chokepoints**, and deep-dive **at most 2**.
  Fewer, better-evidenced chokepoints beat a long list. "Nothing qualifies" is a valid answer.

## Evidence rules

- **Primary (P):** a company's own filings, releases, investor decks, and its own executives on
  calls; a customer's or competitor's filing naming the input; government notices. Only P can
  support a step.
- **Lead (L):** trade press, analyst notes, social posts (the skill's content counts here), and
  anything you can't date or trace to a primary source. A lead can rank a chokepoint, never prove
  a step.
- **Your own knowledge** may draw the map and choose where to look. It is never evidence.
- For each P item give: who said it, the document, its date, the URL, and the **exact sentence**
  quoted. Quote only text you actually read in this session.
- Layers are exact: feedstock, material, component, module, system and equipment are different
  things. A source that blurs them supports none it doesn't name.
- Copies of one announcement count as one source. Share prices are never evidence.

## For each chokepoint, give

1. **The chain:** from the demand driver down to the constrained layer, one hop per line, with
   the strength of each hop's evidence (P, L or map).
2. **The six steps**, each marked unexamined, lead, primary or contradicted, with its evidence:
   - **Constraint:** what exactly can't be supplied, at which layer, in what unit?
   - **Demand against supply:** evidence that demand over the horizon exceeds *qualified*
     capacity, not merely that demand is strong.
   - **Relief:** what would ease it, and how long would that take? Qualification time is
     usually the binding term.
   - **Control:** who holds the constrained capacity, and what share?
   - **Capture:** who books the economics (a listed holder, a private one, a parent, a state)?
   - **Invalidation:** what observations would show it is not a chokepoint?
3. **Three separate verdicts:** physical scarcity, economic capture, investability (is the holder
   listed, financed without a dilution overhang, able to sell under export controls?).
4. **Bear checks** for each deep-dive: dilution, GAAP margins, customer concentration, cash
   against debt, a second source qualifying, an architecture that bypasses the input, demand
   pull-forward, policy reversal, and a layer error.
5. **Kill criteria:** the dated observables that would kill it.
6. **One or two predictions:** "By <date, at most 6 months out>, <observable> will <direction or
   threshold>, as shown by <a named primary source type>". Never a share price.
7. **Origin:** did this chokepoint come from the skill's theses, from your own research this
   session, or both? Say which, plainly.

## Also give

- **Rejected:** candidates you considered and set aside, each with its reason and source.
- **Next questions:** at most five, each with where to look.
- **Run notes:** sources you couldn't reach, claims you couldn't verify, the tool calls used.

No buy or sell language, no position sizing, no price targets. This is evidence, not a trade.
