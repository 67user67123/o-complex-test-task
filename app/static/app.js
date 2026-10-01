"use strict";

(() => {
  const byId = (id) => document.getElementById(id);
  const form = byId("suggest-form");
  const message = byId("message");
  const history = byId("history");
  const submitButton = byId("submit-button");
  const exampleSelect = byId("example-select");
  const reply = byId("client-reply");
  const copyButton = byId("copy-button");
  let examples = [];
  let pending = false;
  let resultInput = null;
  let copyResetTimer;

  const inputKey = () => JSON.stringify([message.value, history.value]);
  const formatNumber = (value) => new Intl.NumberFormat("ru-RU").format(value);
  const seconds = (value) => `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value / 1000)} с`;

  function setError(text) {
    const box = byId("form-error");
    box.textContent = text;
    box.hidden = !text;
  }

  function updateInputState() {
    byId("message-count").textContent = `${formatNumber(message.value.length)} / 6 000`;
    const stale = resultInput !== null && resultInput !== inputKey();
    byId("stale-notice").hidden = !stale;
    byId("results-panel").classList.toggle("is-stale", stale);
    copyButton.disabled = resultInput === null || stale || !reply.value.trim();
    if (stale) {
      byId("copy-label").textContent = "Скопировать";
      byId("copy-status").textContent = "";
    }
  }

  function parseHistory(text) {
    if (!text.trim()) return [];
    const turns = [];
    const lines = text.split(/\r?\n/);
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index].trim();
      if (!line) continue;
      const match = line.match(/^(Клиент|Менеджер)\s*:\s*(.*)$/iu);
      if (match) {
        turns.push({ role: match[1].toLocaleLowerCase("ru-RU") === "клиент" ? "client" : "manager", content: match[2] });
        continue;
      }
      // A short speaker-like prefix is probably a mislabeled turn, not continuation text.
      if (/^[\p{L}][\p{L}\s._-]{0,35}\s*:/u.test(line) && !/^https?:\/\//i.test(line)) {
        throw new Error(`Строка ${index + 1} истории: используйте автора «Клиент:» или «Менеджер:».`);
      }
      if (!turns.length) {
        throw new Error(`Строка ${index + 1} истории должна начинаться с «Клиент:» или «Менеджер:».`);
      }
      turns[turns.length - 1].content += `${turns[turns.length - 1].content ? "\n" : ""}${line}`;
    }
    if (turns.some((turn) => !turn.content.trim())) {
      throw new Error("В истории есть пустая реплика. Добавьте текст после имени автора или удалите эту строку.");
    }
    if (turns.length > 30) {
      throw new Error("Оставьте в истории не более 30 последних реплик.");
    }
    if (turns.some((turn) => turn.content.length > 6000)) {
      throw new Error("Одна из реплик истории длиннее 6 000 знаков. Сократите ее до ключевых сведений.");
    }
    if (turns.reduce((total, turn) => total + turn.content.length, 0) > 20000) {
      throw new Error("Сократите историю переписки до 20 000 знаков.");
    }
    return turns;
  }

  async function requestJson(url, options = {}) {
    let response;
    const headers = { Accept: "application/json", ...options.headers };
    const accessKey = byId("access-key").value.trim();
    if (url !== "/health" && accessKey) headers.Authorization = `Bearer ${accessKey}`;
    try {
      response = await fetch(url, { ...options, headers });
    } catch {
      throw new Error("Не удалось связаться с сервисом. Убедитесь, что он запущен, и повторите запрос.");
    }
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error("Сервис вернул неожиданный ответ. Повторите запрос через несколько секунд.");
    }
    if (!response.ok) {
      if (response.status === 401) {
        byId("health-details").open = true;
        byId("access-key").focus();
        throw new Error("Введите ключ доступа к сервису в настройках подключения выше.");
      }
      const apiMessage = data?.error?.message;
      if (typeof apiMessage === "string" && apiMessage) throw new Error(apiMessage);
      if (response.status === 422) throw new Error("Проверьте обращение и формат истории: обе роли должны быть подписаны, а реплики — содержать текст.");
      throw new Error("Не удалось подготовить ответ. Проверьте готовность сервиса и попробуйте еще раз.");
    }
    return data;
  }

  async function checkHealth() {
    const refresh = byId("refresh-health");
    refresh.disabled = true;
    try {
      const data = await requestJson("/health");
      const ready = data.status === "ok";
      byId("health-label").textContent = ready ? "Сервис готов к работе" : "Сервис требует подготовки";
      byId("status-dot").className = `status-dot ${ready ? "ready" : "warning"}`;
      const notices = [];
      if (data.ollama?.message) notices.push(data.ollama.message);
      if (data.index?.message) notices.push(data.index.message);
      byId("health-description").textContent = ready
        ? "Локальная модель доступна, база знаний подготовлена для поиска."
        : notices.join("\n") || "Проверьте, что локальная модель запущена, а база знаний проиндексирована. Инструкция по запуску находится в README.";
      byId("generation-model").textContent = data.model || "Не указана";
      byId("embedding-model").textContent = data.embedding_model || "Не указана";
      byId("index-state").textContent = Number.isFinite(data.index?.count) ? `${formatNumber(data.index.count)} фрагментов` : "Пока не готова";
      byId("health-models").hidden = false;
      if (!ready) byId("health-details").open = true;
    } catch (error) {
      byId("health-label").textContent = "Сервис недоступен";
      byId("status-dot").className = "status-dot warning";
      byId("health-description").textContent = error.message;
      byId("health-models").hidden = true;
      byId("health-details").open = true;
    } finally {
      refresh.disabled = false;
    }
  }

  async function loadExamples() {
    try {
      const data = await requestJson("/examples");
      if (!Array.isArray(data)) throw new Error("Некорректный список примеров.");
      examples = data.filter((example) => typeof example.id === "string" && typeof example.title === "string" && typeof example.message === "string" && Array.isArray(example.history));
      exampleSelect.replaceChildren(new Option("Выберите обращение…", ""));
      for (const example of examples) exampleSelect.add(new Option(example.title, example.id));
      exampleSelect.disabled = examples.length === 0;
      byId("example-notice").hidden = true;
      if (!examples.length) exampleSelect.replaceChildren(new Option("Примеры пока не добавлены", ""));
    } catch (error) {
      exampleSelect.replaceChildren(new Option("Примеры недоступны", ""));
      exampleSelect.disabled = true;
      const notice = byId("example-notice");
      notice.textContent = error.message.startsWith("Введите ключ") ? error.message : "Можно ввести свое обращение в полях ниже.";
      notice.hidden = false;
    }
  }

  function setPending(value) {
    pending = value;
    submitButton.disabled = value;
    byId("submit-label").textContent = value ? "Готовим ответ…" : "Подготовить ответ";
    submitButton.querySelector(".button-spinner").hidden = !value;
    submitButton.querySelector(".submit-arrow").hidden = value;
    byId("loading-note").hidden = !value;
    byId("results-panel").setAttribute("aria-busy", String(value));
  }

  function showResult(data, submittedInput) {
    if (typeof data.client_reply !== "string" || !data.client_reply.trim() || typeof data.manager_tip !== "string" || !data.manager_tip.trim()) {
      throw new Error("Модель вернула неполный ответ. Повторите запрос.");
    }
    reply.value = data.client_reply;
    reply.hidden = false;
    byId("reply-placeholder").hidden = true;
    byId("manager-tip").textContent = data.manager_tip;
    byId("manager-tip").hidden = false;
    byId("tip-placeholder").hidden = true;
    byId("copy-label").textContent = "Скопировать";
    byId("copy-status").textContent = "";
    const list = byId("sources-list");
    list.replaceChildren();
    const kinds = { faq: "Вопрос и ответ", product: "Товар / услуга", upsell: "Дополнение" };
    const sources = Array.isArray(data.sources) ? data.sources : [];
    for (const source of sources) {
      const row = document.createElement("li");
      const title = document.createElement("span");
      title.className = "source-title";
      title.textContent = source.title || source.id || "Фрагмент базы";
      const kind = document.createElement("span");
      kind.className = "source-kind";
      kind.textContent = kinds[source.kind] || "База знаний";
      row.append(title, kind);
      list.append(row);
    }
    byId("sources-summary").textContent = `Источники ответа · ${sources.length}`;
    byId("sources-details").hidden = false;
    byId("sources-details").open = false;
    document.querySelector(".sources-intro").textContent = sources.length
      ? "Фрагменты базы знаний, найденные для этого обращения."
      : "Подходящих сведений в базе не найдено. В ответе может потребоваться уточнение.";
    const timing = data.timings || {};
    const parts = [];
    if (Number.isFinite(timing.retrieval_ms)) parts.push(`Поиск: ${seconds(timing.retrieval_ms)}`);
    if (Number.isFinite(timing.generation_ms)) parts.push(`Подготовка: ${seconds(timing.generation_ms)}`);
    byId("timing-details").textContent = parts.join(" · ");
    byId("result-time").hidden = !Number.isFinite(timing.total_ms);
    byId("result-time").textContent = Number.isFinite(timing.total_ms) ? `За ${seconds(timing.total_ms)}` : "";
    resultInput = submittedInput;
    updateInputState();
    if (window.matchMedia("(max-width: 780px)").matches) {
      byId("results-panel").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (pending) return;
    setError("");
    let turns;
    try {
      if (!message.value.trim()) throw new Error("Добавьте сообщение клиента, на которое нужно ответить.");
      turns = parseHistory(history.value);
    } catch (error) {
      setError(error.message);
      return;
    }
    const submittedInput = inputKey();
    const payload = { message: message.value.trim(), history: turns };
    setPending(true);
    try {
      const data = await requestJson("/suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      showResult(data, submittedInput);
    } catch (error) {
      setError(error.message);
    } finally {
      setPending(false);
    }
  });

  exampleSelect.addEventListener("change", () => {
    const example = examples.find((item) => item.id === exampleSelect.value);
    if (!example) return;
    message.value = example.message;
    history.value = example.history.map((turn) => `${turn.role === "manager" ? "Менеджер" : "Клиент"}: ${turn.content}`).join("\n");
    setError("");
    updateInputState();
    message.focus();
  });

  for (const input of [message, history]) {
    input.addEventListener("input", () => {
      exampleSelect.value = "";
      setError("");
      updateInputState();
    });
    input.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        if (!pending) form.requestSubmit();
      }
    });
  }

  reply.addEventListener("input", () => {
    byId("copy-label").textContent = "Скопировать";
    updateInputState();
  });

  copyButton.addEventListener("click", async () => {
    if (copyButton.disabled) return;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(reply.value);
      } else {
        reply.focus();
        reply.select();
        if (!document.execCommand("copy")) throw new Error("Copy failed");
      }
      byId("copy-label").textContent = "Скопировано";
      byId("copy-status").textContent = "Ответ клиенту скопирован.";
      clearTimeout(copyResetTimer);
      copyResetTimer = setTimeout(() => { byId("copy-label").textContent = "Скопировать"; }, 2200);
    } catch {
      reply.focus();
      reply.select();
      byId("copy-label").textContent = "Нажмите Ctrl+C";
      byId("copy-status").textContent = "Текст ответа выделен. Нажмите Ctrl+C, чтобы скопировать его.";
    }
  });

  byId("refresh-health").addEventListener("click", checkHealth);
  byId("apply-key").addEventListener("click", () => {
    setError("");
    void loadExamples();
  });
  byId("access-key").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      byId("apply-key").click();
    }
  });
  updateInputState();
  void Promise.allSettled([checkHealth(), loadExamples()]);
})();
