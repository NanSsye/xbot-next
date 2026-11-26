import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./ui/App";
import "./styles.css";
import "./styles-extra.css";
import "./styles-hardening.css";
import "./styles-content.css";
import "./styles-centers.css";
import "./styles-motion.css";
import "./styles-responsive.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
