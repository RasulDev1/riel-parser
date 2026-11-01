/** Пересборка стилей: npx tailwindcss@3.4.17 -c ui/tailwind.config.js -i ui/src.css -o ui/app.css --minify */
module.exports = {
  content: [__dirname + "/index.html", __dirname + "/app.js"],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: "#10A37F", 50: "#E8F6F1", 600: "#0D8A6B" },
        ink: "#0F1720",
        muted: "#64748B",
        line: "#E3E7EC",
        canvas: "#F6F7F9",
      },
    },
  },
};
