# Animated Backgrounds & Scroll Cinematics — Source Map

Drop-in component sources for animated hero/background effects and scroll-driven
cinematics. The styles database (`data/styles.csv`) carries the *style knowledge*;
this file maps each effect to real, free implementation code so nothing gets
hand-rolled from memory. Added 2026-07-02 after a gap review against commercial
skill packs (skillsui.app) — every effect below is available free.

## How to use

1. Pick the effect for the page's ONE bold moment (Von Restorff: one, not five).
2. Copy the component from the source below; adapt tokens to the project palette.
3. Always: `prefers-reduced-motion` fallback, pause canvas/WebGL when tab hidden,
   keep background opacity low enough that foreground text holds 4.5:1.

## Effect → source

| Effect | Source | Notes |
|--------|--------|-------|
| Aurora / mesh gradient drift | [react-bits Aurora](https://reactbits.dev/backgrounds/aurora) ([repo](https://github.com/DavidHDev/react-bits)) · [shadergradient](https://github.com/ruucm/shadergradient) | WebGL; shadergradient has a no-code editor for tuning |
| Liquid / flowing background | [react-bits](https://reactbits.dev/) Liquid Chrome / Threads | WebGL shader; heavy — hero only |
| Meteors / shooting stars | [magicui Meteors](https://github.com/magicuidesign/magicui) · [shadcn.io meteors](https://www.shadcn.io/background/meteors) (CSS-only) · [animata shooting stars](https://animata.design/docs/background/animated-beam) | CSS-only variant is the performance-safe default |
| Constellation / interactive dot web | [tsParticles](https://github.com/tsparticles/tsparticles) links preset · [Vanta.js NET](https://github.com/tengbao/vanta) | Cursor-reactive; cap particle count on mobile |
| Radial glow / concentric rings | [magicui](https://github.com/magicuidesign/magicui) Ripple / Orbiting Circles | SVG + CSS, cheap |
| Particles / sparkles / grid patterns | [magicui](https://github.com/magicuidesign/magicui) Particles, Animated Grid Pattern, Retro Grid | MIT, shadcn-style copy-paste |
| Broad free catalog (110+ components) | [motion-primitives](https://github.com/itsjwill/motion-primitives-website) | Open-source alternative to Aceternity UI / Magic UI paid tiers |
| Matrix digital rain | canvas + `requestAnimationFrame` (see `styles.csv` No 89 for the recipe) | ~40 lines vanilla; no dependency needed |

## Scroll-driven cinematic hero (video scrub)

Technique, not a library: render video frames to a `<canvas>` (or `currentTime`
scrub) keyed to scroll progress.

- [GSAP ScrollTrigger](https://github.com/greensock/GSAP) — the scrub engine (free tier covers this)
- [Lenis](https://github.com/darkroomengineering/lenis) — smooth scroll so the scrub doesn't stutter
- Recipe: pre-export frames as WebP sequence → draw to canvas on `scrollTrigger.progress`; the Apple AirPods page pattern
- Budget: frame sequence is the LCP risk — lazy-load below-fold sequences, poster image first

## License notes

magicui, react-bits, tsParticles, Vanta, Lenis, motion-primitives: MIT.
GSAP: free "no-charge" license covers ScrollTrigger scrub use.
Aceternity UI is per-component licensed — the free open-source options above cover
the same effects; reach for Aceternity only with a license check.
