import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { V2App } from "./v2";
import "./styles.css";
import "./v2.css";

const path = window.location.pathname.replace(/\/+$/, "") || "/";
const useV2 = path === "/v2" || window.location.hash.startsWith("#v2/");

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {useV2 ? <V2App /> : <App />}
  </React.StrictMode>
);
