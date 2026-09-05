/** @type {import('tailwindcss').Config} */

// Shared midnight-ocean palette. Semantic token names remain stable so the
// decision and architecture components keep their existing contracts.
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        obsidian: '#0B1720',
        surface: '#12232D',
        emerald: {
          DEFAULT: '#62C6D7',
          dim: 'rgba(98, 198, 215, 0.14)',
          line: 'rgba(98, 198, 215, 0.38)',
        },
        indigo: {
          DEFAULT: '#F0B66E',
          dim: 'rgba(240, 182, 110, 0.14)',
          line: 'rgba(240, 182, 110, 0.38)',
        },
        coral: {
          DEFAULT: '#E58B84',
          dim: 'rgba(229, 139, 132, 0.14)',
          line: 'rgba(229, 139, 132, 0.38)',
        },
        slateink: {
          DEFAULT: '#AEBFC7',
          dim: 'rgba(174, 191, 199, 0.12)',
          line: 'rgba(174, 191, 199, 0.30)',
        },
      },
      fontFamily: {
        // General headers, subtext and navigation. Geist Sans is preferred;
        // Plus Jakarta Sans (the one actually loaded, via Google Fonts) is the
        // fallback that ships today, ahead of the system stack. No mono type
        // appears outside data values -- see `mono` below and `font-tnum`.
        // Plus Jakarta Sans is the family actually loaded (Google Fonts, see
        // index.html) -- it leads the stack rather than a name nothing serves,
        // which is what "Geist Sans" would be without self-hosting Vercel's
        // font package. Swap this token alone if Geist is added later.
        display: ['"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
        body: ['"Plus Jakarta Sans"', 'system-ui', '-apple-system', 'sans-serif'],
        // Restricted to telemetry, formulas and numeric readouts -- never body
        // copy or headings. Pair with the `.font-tnum` utility (index.css) for
        // tabular-figure rendering on any value that animates or updates live.
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.06em' }],
      },
      maxWidth: {
        content: '78rem',
      },
      transitionTimingFunction: {
        // The single easing curve used for every entrance in the site.
        entrance: 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(14px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'pulse-ring': {
          '0%': { opacity: '0.55', transform: 'scale(0.94)' },
          '70%': { opacity: '0', transform: 'scale(1.25)' },
          '100%': { opacity: '0', transform: 'scale(1.25)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.5s cubic-bezier(0.22, 1, 0.36, 1) both',
        'pulse-ring': 'pulse-ring 2.4s cubic-bezier(0.22, 1, 0.36, 1) infinite',
      },
    },
  },
  plugins: [],
};
