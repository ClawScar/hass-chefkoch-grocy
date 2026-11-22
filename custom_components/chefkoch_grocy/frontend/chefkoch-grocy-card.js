const DOMAIN = "chefkoch_grocy";

const ACTION_LABELS = {
  created: "neu angelegt",
  updated: "aktualisiert",
  skipped: "bereits vorhanden",
};

class ChefkochGrocyCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._urls = "";
    this._busy = false;
    this._status = null;
    this._rendered = false;
  }

  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    this._config = config || {};
    if (this._rendered) this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first && !this._rendered) this._render();
  }

  getCardSize() {
    return 3;
  }

  _escape(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  _render() {
    this._rendered = true;
    const title = this._config && this._config.title ? this._config.title : "Chefkoch → Grocy";

    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 16px; box-sizing: border-box; }
        .title { font-size: 1.1rem; font-weight: 500; margin-bottom: 10px; }
        textarea {
          width: 100%; box-sizing: border-box; min-height: 58px; resize: vertical;
          padding: 8px 10px; font: inherit; font-size: 0.95rem;
          color: var(--primary-text-color);
          background: var(--card-background-color);
          border: 1px solid var(--divider-color); border-radius: 6px;
        }
        textarea:focus { outline: none; border-color: var(--primary-color); }
        .row { display: flex; align-items: center; gap: 12px; margin-top: 12px; flex-wrap: wrap; }
        button {
          font: inherit; font-weight: 500; padding: 8px 18px; border: none; border-radius: 6px;
          background: var(--primary-color); color: var(--text-primary-color, #fff); cursor: pointer;
        }
        button[disabled] { opacity: 0.6; cursor: default; }
        .hint { color: var(--secondary-text-color); font-size: 0.85rem; }
        .status { margin-top: 10px; font-size: 0.9rem; line-height: 1.45; white-space: pre-line; }
        .status.error { color: var(--error-color, #db4437); }
        .status.ok { color: var(--success-color, #43a047); }
        .status.busy { color: var(--secondary-text-color); }
      </style>
      <ha-card>
        <div class="title">${this._escape(title)}</div>
        <textarea id="urls" placeholder="https://www.chefkoch.de/rezepte/… (eine URL pro Zeile)"></textarea>
        <div class="row">
          <button id="go">Importieren</button>
          <span class="hint">Nur Rezepte – keine Zutaten, keine Produkte.</span>
        </div>
        <div class="status" id="status"></div>
      </ha-card>`;

    const area = this.shadowRoot.getElementById("urls");
    area.value = this._urls;
    area.addEventListener("input", (event) => {
      this._urls = event.target.value;
    });
    this.shadowRoot.getElementById("go").addEventListener("click", () => this._import());
    this._updateStatus();
  }

  _updateStatus() {
    const node = this.shadowRoot.getElementById("status");
    const button = this.shadowRoot.getElementById("go");
    if (!node || !button) return;

    button.disabled = this._busy;
    button.textContent = this._busy ? "Importiere …" : "Importieren";

    if (!this._status) {
      node.textContent = "";
      node.className = "status";
      return;
    }
    node.textContent = this._status.text;
    node.className = `status ${this._status.type || ""}`;
  }

  async _import() {
    if (this._busy) return;

    if (!this._urls.trim()) {
      this._status = { type: "error", text: "Bitte eine Chefkoch-URL einfügen." };
      this._updateStatus();
      return;
    }

    this._busy = true;
    this._status = { type: "busy", text: "Rezept wird geladen …" };
    this._updateStatus();

    try {
      const answer = await this._hass.callService(
        DOMAIN,
        "import_recipe",
        { url: this._urls },
        undefined,
        false,
        true
      );
      const results =
        (answer && answer.response && answer.response.results) ||
        (answer && answer.results) ||
        [];
      const imported = results.filter((item) => !item.error);
      const failed = results.filter((item) => item.error);

      if (!results.length) {
        this._status = { type: "error", text: "Der Import hat keine Antwort geliefert." };
      } else if (!imported.length) {
        this._status = { type: "error", text: `Fehlgeschlagen: ${failed[0].error}` };
      } else {
        const lines = imported.map(
          (item) => `• ${item.name} (${ACTION_LABELS[item.action] || item.action})`
        );
        if (failed.length) {
          lines.push(`Fehler: ${failed.map((item) => item.error).join(" ")}`);
        }
        this._status = {
          type: failed.length ? "error" : "ok",
          text: lines.join("\n"),
        };
      }
    } catch (err) {
      this._status = {
        type: "error",
        text: (err && err.message) || "Unbekannter Fehler beim Import.",
      };
    } finally {
      this._busy = false;
      this._updateStatus();
    }
  }
}

if (!customElements.get("chefkoch-grocy-card")) {
  customElements.define("chefkoch-grocy-card", ChefkochGrocyCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "chefkoch-grocy-card")) {
  window.customCards.push({
    type: "chefkoch-grocy-card",
    name: "Chefkoch → Grocy",
    description: "Rezepte von Chefkoch per URL in Grocy importieren.",
    preview: false,
  });
}
