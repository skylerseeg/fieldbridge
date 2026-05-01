import React from "react";
import ReactDOM from "react-dom/client";

import { Root } from "@/Root";

import "@/index.css";

// Set up the axios interceptors (refresh-on-401) as a side effect.
import "@/lib/api";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
