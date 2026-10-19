export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: { page: "#F6F7F5", ink: "#17212B", muted: "#66717D", line: "#DCE2E3",
                accent: "#176B65", fail: "#B54747", ok: "#287653", warn: "#A66A24" },
      fontFamily: {
        sans: ['"IBM Plex Sans"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
        serif: ['"Newsreader"', "Georgia", "serif"],
      },
      borderRadius: { DEFAULT: "3px", md: "4px", lg: "5px" },
    },
  },
  plugins: [],
};
