// alex_XXXX_API nodes — "Refresh Models" button.
//
// Adds a button widget to every API-backed node. Clicking it POSTs the node's
// current 🔑 openai_api_key + 🌐 endpoint to /alex_minimax/refresh_models; the
// backend calls GET {endpoint}/models, caches the result per endpoint, and
// returns the model list, which we inject into the 🤖 model combo live.
//
// On node creation we also sync the combo from the server-side cache
// (GET /alex_minimax/models_cache) so refreshes done in another tab/session
// show up without a full page reload.

import { app } from "../../../scripts/app.js";

const API_NODES = ["alex_h3_prompt_API", "alex_h3_skill_API", "alex_music3_API", "alex_qwen_image21_API"];
const REFRESH_URL = "/alex_minimax/refresh_models";
const CACHE_URL = "/alex_minimax/models_cache";

function findWidget(node, name) {
  return (node.widgets || []).find((w) => w.name === name);
}

function applyModels(modelWidget, models) {
  if (!modelWidget || !Array.isArray(models) || models.length === 0) return false;
  if (!modelWidget.options) modelWidget.options = {};
  modelWidget.options.values = models;
  if (!models.includes(modelWidget.value)) {
    modelWidget.value = models[0];
  }
  return true;
}

app.registerExtension({
  name: "Alex.MiniMax.API.RefreshModels",

  beforeRegisterNodeDef(nodeType, nodeData) {
    if (!API_NODES.includes(nodeData.name)) return;

    const origOnCreated = nodeType.prototype.onNodeCreated;

    nodeType.prototype.onNodeCreated = function () {
      const r = origOnCreated ? origOnCreated.apply(this, arguments) : undefined;
      const node = this;

      const btn = node.addWidget(
        "button",
        "\u{1F504} Refresh Models",
        "alex_minimax_refresh_models",
        async () => {
          const wKey = findWidget(node, "\u{1F511} openai_api_key");
          const wEp = findWidget(node, "\u{1F310} endpoint");
          const wModel = findWidget(node, "\u{1F916} model");

          btn.label = "\u23F3 Refreshing...";
          node.setDirtyCanvas(true, false);

          try {
            const resp = await fetch(REFRESH_URL, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                endpoint: wEp ? wEp.value : "",
                api_key: wKey ? wKey.value : "",
              }),
            });
            const data = await resp.json();

            if (data.ok && applyModels(wModel, data.models)) {
              btn.label = `\u{1F504} Refresh Models (${data.models.length})`;
            } else {
              btn.label = `\u26A0 ${(data.error || "no models").slice(0, 60)}`;
            }
          } catch (e) {
            btn.label = `\u26A0 ${String(e.message || e).slice(0, 60)}`;
          }

          node.setDirtyCanvas(true, true);
        }
      );
      btn.serialize = false;

      // Sync combo from the server cache (models cached from previous
      // sessions or other tabs). Silent; keeps the default list on failure.
      (async () => {
        try {
          const resp = await fetch(CACHE_URL);
          const data = await resp.json();
          if (!data.ok || !data.cache) return;

          const wEp = findWidget(node, "\u{1F310} endpoint");
          const wModel = findWidget(node, "\u{1F916} model");
          const ep = (wEp && wEp.value ? wEp.value : "").trim().replace(/\/+$/, "");

          let models = [];
          if (ep && Array.isArray(data.cache[ep])) {
            models = data.cache[ep];
          } else {
            for (const list of Object.values(data.cache)) models = models.concat(list);
            models = [...new Set(models)].sort();
          }
          if (applyModels(wModel, models)) {
            btn.label = `\u{1F504} Refresh Models (${models.length})`;
            node.setDirtyCanvas(true, false);
          }
        } catch (e) {
          /* keep defaults */
        }
      })();

      return r;
    };
  },
});
