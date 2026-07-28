import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

// Apply the saved theme before first paint (no flash). Default to light to match the design.
const savedTheme = localStorage.getItem("wallbreaker.theme");
document.documentElement.dataset.theme =
  savedTheme === "dark" || savedTheme === "light" ? savedTheme : "light";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
