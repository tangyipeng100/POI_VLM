const state = {
  samples: [],
  index: 0,
  selectedPois: [],
  action: "go_to_poi",
  rotateDirection: "left",
  dirty: false,
  zoom: 1,
  fitWidth: true,
};

const els = {
  subtitle: document.getElementById("subtitle"),
  questionImage: document.getElementById("questionImage"),
  imageViewport: document.getElementById("imageViewport"),
  zoomOutBtn: document.getElementById("zoomOutBtn"),
  zoomInBtn: document.getElementById("zoomInBtn"),
  zoomResetBtn: document.getElementById("zoomResetBtn"),
  zoomFitBtn: document.getElementById("zoomFitBtn"),
  zoomLabel: document.getElementById("zoomLabel"),
  sampleId: document.getElementById("sampleId"),
  listSummary: document.getElementById("listSummary"),
  routeMeta: document.getElementById("routeMeta"),
  saveState: document.getElementById("saveState"),
  prevBtn: document.getElementById("prevBtn"),
  nextBtn: document.getElementById("nextBtn"),
  previewBtn: document.getElementById("previewBtn"),
  saveBtn: document.getElementById("saveBtn"),
  poiButtons: document.getElementById("poiButtons"),
  poiList: document.getElementById("poiList"),
  rotateAngle: document.getElementById("rotateAngle"),
  confidence: document.getElementById("confidence"),
  note: document.getElementById("note"),
  sampleStrip: document.getElementById("sampleStrip"),
  poiSection: document.getElementById("poiSection"),
  rotateSection: document.getElementById("rotateSection"),
  rotLeft: document.getElementById("rotLeft"),
  rotRight: document.getElementById("rotRight"),
  previewModal: document.getElementById("previewModal"),
  previewBackdrop: document.getElementById("previewBackdrop"),
  previewGrid: document.getElementById("previewGrid"),
  previewSummary: document.getElementById("previewSummary"),
  closePreviewBtn: document.getElementById("closePreviewBtn"),
};

function currentSample() {
  return state.samples[state.index];
}

function normalizePoiNumbers(annotation = {}) {
  const raw = Array.isArray(annotation.poi_numbers)
    ? annotation.poi_numbers
    : annotation.poi_number !== undefined && annotation.poi_number !== null
      ? [annotation.poi_number]
      : [];
  return [...new Set(raw
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value)))]
    .sort((a, b) => a - b);
}

function poiMarker(annotation = {}) {
  const numbers = normalizePoiNumbers(annotation);
  return numbers.length ? `POI ${numbers.join("/")}` : "POI -";
}

function setDirty(value) {
  state.dirty = value;
  const sample = currentSample();
  const hasAnnotation = sample && sample.annotation;
  els.saveState.className = value ? "unsaved" : hasAnnotation ? "saved" : "";
  els.saveState.textContent = value ? "未保存" : hasAnnotation ? "已保存" : "未标注";
}

async function loadSamples() {
  const res = await fetch("/api/samples");
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  state.samples = data.samples;
  state.index = Math.min(data.next_unlabeled_index ?? 0, Math.max(0, state.samples.length - 1));
  els.subtitle.textContent = `${data.annotated_count}/${data.total} 已标注`;
  render();
}

function render() {
  const sample = currentSample();
  if (!sample) {
    els.subtitle.textContent = "没有样本";
    return;
  }

  els.questionImage.src = sample.question_image_url;
  els.sampleId.textContent = `${sample.sample_id}  (${state.index + 1}/${state.samples.length})`;

  const route = sample.route || {};
  const gps = sample.gps || {};
  els.routeMeta.innerHTML = [
    `frame: ${sample.frame_index}, gps: ${route.gps_frame ?? gps.frame ?? "-"}`,
    `passed: ${fmt(route.passed_m)}m, remaining: ${fmt(route.remaining_m)}m`,
    `heading: ${fmt(route.heading_deg)}°, dist-to-route: ${fmt(route.distance_to_route_m)}m`,
  ].join("<br>");

  const annotation = sample.annotation || {};
  state.action = annotation.action || "go_to_poi";
  state.selectedPois = normalizePoiNumbers(annotation);
  state.rotateDirection = annotation.rotate_direction || "left";
  els.rotateAngle.value = annotation.rotate_angle_deg ?? 30;
  els.confidence.value = annotation.confidence || "medium";
  els.note.value = annotation.note || "";

  document.querySelectorAll("input[name='action']").forEach((input) => {
    input.checked = input.value === state.action;
  });

  renderPoiControls(sample);
  renderRotateControls();
  renderSampleStrip();
  updateModeVisibility();
  applyZoom();
  setDirty(false);
}

function fmt(value) {
  if (value === undefined || value === null || Number.isNaN(value)) return "-";
  return Number(value).toFixed(1);
}

function renderPoiControls(sample) {
  els.poiButtons.innerHTML = "";
  els.poiList.innerHTML = "";
  const pois = sample.pois || [];

  if (!pois.length) {
    els.poiButtons.innerHTML = "<p class='hint'>这一帧没有 POI，建议标 skip 或 rotate。</p>";
    return;
  }

  pois.forEach((poi) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = poi.number;
    btn.className = state.selectedPois.includes(poi.number) ? "selected" : "";
    btn.title = `${poi.color} (${poi.x}, ${poi.y})`;
    btn.addEventListener("click", () => selectPoi(poi.number));
    els.poiButtons.appendChild(btn);

    const item = document.createElement("div");
    item.textContent = `POI ${poi.number}: ${poi.color}, (${poi.x}, ${poi.y}), ${poi.edge_type}`;
    els.poiList.appendChild(item);
  });
}

function renderRotateControls() {
  els.rotLeft.classList.toggle("selected", state.rotateDirection === "left");
  els.rotRight.classList.toggle("selected", state.rotateDirection === "right");
}

function renderSampleStrip() {
  els.sampleStrip.innerHTML = "";
  const annotated = state.samples.filter((sample) => sample.annotation).length;
  els.listSummary.textContent = `${annotated}/${state.samples.length}`;
  state.samples.forEach((sample, idx) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sample-dot";
    if (idx === state.index) btn.classList.add("active");
    if (sample.annotation) {
      btn.classList.add(sample.annotation.action === "skip" ? "skip" : "done");
    }
    const action = sample.annotation?.action;
    const marker = action === "go_to_poi"
      ? poiMarker(sample.annotation)
      : action === "rotate"
        ? `旋转 ${sample.annotation.rotate_direction === "left" ? "左" : "右"}${sample.annotation.rotate_angle_deg}°`
        : action === "skip"
          ? "丢弃"
          : "未标";
    btn.textContent = `${idx + 1}. ${sample.sample_id.replace("debug_raw_", "")}  ${marker}`;
    btn.title = sample.sample_id;
    btn.addEventListener("click", () => {
      state.index = idx;
      render();
    });
    els.sampleStrip.appendChild(btn);
  });
}

function clampZoom(value) {
  return Math.max(0.35, Math.min(3.5, value));
}

function setZoom(value, { fitWidth = false } = {}) {
  state.zoom = clampZoom(value);
  state.fitWidth = fitWidth;
  applyZoom();
}

function applyZoom() {
  const img = els.questionImage;
  const viewport = els.imageViewport;
  if (!img || !viewport) return;

  if (state.fitWidth) {
    img.style.width = "100%";
    img.style.transform = "none";
    els.zoomLabel.textContent = "适应";
    return;
  }

  img.style.width = `${state.zoom * 100}%`;
  img.style.transform = "none";
  els.zoomLabel.textContent = `${Math.round(state.zoom * 100)}%`;
}

function openPreview() {
  const remaining = state.samples
    .map((sample, index) => ({ sample, index }))
    .filter(({ sample }) => !sample.annotation);

  els.previewSummary.textContent = `剩余 ${remaining.length} / 共 ${state.samples.length} 张`;
  els.previewGrid.innerHTML = "";

  if (!remaining.length) {
    const empty = document.createElement("div");
    empty.className = "preview-empty";
    empty.textContent = "已经全部标注完成。";
    els.previewGrid.appendChild(empty);
  } else {
    remaining.forEach(({ sample, index }) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "preview-card";
      card.addEventListener("click", () => {
        state.index = index;
        closePreview();
        render();
      });

      const img = document.createElement("img");
      img.loading = "lazy";
      img.src = sample.question_image_url;
      img.alt = sample.sample_id;
      card.appendChild(img);

      const caption = document.createElement("div");
      caption.className = "preview-caption";
      const route = sample.route || {};
      caption.innerHTML = `<strong>${index + 1}. ${sample.sample_id}</strong><span>${fmt(route.passed_m)}m</span>`;
      card.appendChild(caption);

      els.previewGrid.appendChild(card);
    });
  }

  els.previewModal.hidden = false;
}

function closePreview() {
  els.previewModal.hidden = true;
}

function updateModeVisibility() {
  els.poiSection.style.display = state.action === "go_to_poi" ? "" : "none";
  els.rotateSection.style.display = state.action === "rotate" ? "" : "none";
}

function selectPoi(number) {
  state.action = "go_to_poi";
  if (state.selectedPois.includes(number)) {
    state.selectedPois = state.selectedPois.filter((value) => value !== number);
  } else {
    state.selectedPois = [...state.selectedPois, number].sort((a, b) => a - b);
  }
  document.querySelector("input[name='action'][value='go_to_poi']").checked = true;
  renderPoiControls(currentSample());
  updateModeVisibility();
  setDirty(true);
}

function setAction(action) {
  state.action = action;
  updateModeVisibility();
  setDirty(true);
}

function setRotateDirection(direction) {
  state.action = "rotate";
  state.rotateDirection = direction;
  document.querySelector("input[name='action'][value='rotate']").checked = true;
  renderRotateControls();
  updateModeVisibility();
  setDirty(true);
}

async function saveAnnotation({ advance = false } = {}) {
  const sample = currentSample();
  if (!sample) return;
  const poiNumbers = state.action === "go_to_poi" ? [...state.selectedPois] : [];

  const payload = {
    sample_id: sample.sample_id,
    action: state.action,
    poi_number: poiNumbers.length ? poiNumbers[0] : null,
    poi_numbers: poiNumbers,
    rotate_direction: state.action === "rotate" ? state.rotateDirection : null,
    rotate_angle_deg: state.action === "rotate" ? Number(els.rotateAngle.value || 0) : null,
    confidence: els.confidence.value,
    note: els.note.value.trim(),
  };

  if (payload.action === "go_to_poi" && !payload.poi_numbers.length) {
    alert("请至少选择一个 POI，或改成 rotate/skip。");
    return;
  }
  if (payload.action === "rotate" && (!payload.rotate_direction || !payload.rotate_angle_deg)) {
    alert("请填写旋转方向和角度。");
    return;
  }

  const res = await fetch("/api/annotations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    alert(await res.text());
    return;
  }

  const data = await res.json();
  sample.annotation = data.annotation;
  els.subtitle.textContent = `${data.annotated_count}/${data.total} 已标注`;
  setDirty(false);
  renderSampleStrip();

  if (advance) move(1);
}

function move(delta) {
  if (!state.samples.length) return;
  state.index = Math.max(0, Math.min(state.samples.length - 1, state.index + delta));
  render();
}

function adjustAngle(delta) {
  const next = Math.max(0, Math.min(180, Number(els.rotateAngle.value || 0) + delta));
  els.rotateAngle.value = next;
  setDirty(true);
}

document.querySelectorAll("input[name='action']").forEach((input) => {
  input.addEventListener("change", () => setAction(input.value));
});
els.rotLeft.addEventListener("click", () => setRotateDirection("left"));
els.rotRight.addEventListener("click", () => setRotateDirection("right"));
els.rotateAngle.addEventListener("input", () => setDirty(true));
els.confidence.addEventListener("change", () => setDirty(true));
els.note.addEventListener("input", () => setDirty(true));
els.prevBtn.addEventListener("click", () => move(-1));
els.nextBtn.addEventListener("click", () => move(1));
els.previewBtn.addEventListener("click", openPreview);
els.previewBackdrop.addEventListener("click", closePreview);
els.closePreviewBtn.addEventListener("click", closePreview);
els.saveBtn.addEventListener("click", () => saveAnnotation({ advance: true }));
els.zoomOutBtn.addEventListener("click", () => setZoom((state.fitWidth ? 1 : state.zoom) - 0.15));
els.zoomInBtn.addEventListener("click", () => setZoom((state.fitWidth ? 1 : state.zoom) + 0.15));
els.zoomResetBtn.addEventListener("click", () => setZoom(1));
els.zoomFitBtn.addEventListener("click", () => setZoom(1, { fitWidth: true }));
els.imageViewport.addEventListener("wheel", (event) => {
  if (!event.ctrlKey) return;
  event.preventDefault();
  const base = state.fitWidth ? 1 : state.zoom;
  setZoom(base + (event.deltaY < 0 ? 0.12 : -0.12));
}, { passive: false });

document.addEventListener("keydown", (event) => {
  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
    return;
  }
  const key = event.key.toLowerCase();
  if (/^[1-9]$/.test(key)) {
    const number = Number(key);
    const sample = currentSample();
    if ((sample.pois || []).some((poi) => poi.number === number)) selectPoi(number);
  } else if (key === "r") {
    setAction("rotate");
    document.querySelector("input[name='action'][value='rotate']").checked = true;
  } else if (key === "a" || event.key === "ArrowLeft") {
    setRotateDirection("left");
  } else if (key === "l" || event.key === "ArrowRight") {
    setRotateDirection("right");
  } else if (key === "enter") {
    event.preventDefault();
    saveAnnotation({ advance: true });
  } else if (key === "[") {
    adjustAngle(-5);
  } else if (key === "]") {
    adjustAngle(5);
  } else if (key === "j") {
    move(1);
  } else if (key === "k") {
    move(-1);
  } else if (key === "p") {
    openPreview();
  } else if (key === "escape" && !els.previewModal.hidden) {
    closePreview();
  } else if (key === "=" || key === "+") {
    setZoom((state.fitWidth ? 1 : state.zoom) + 0.15);
  } else if (key === "-") {
    setZoom((state.fitWidth ? 1 : state.zoom) - 0.15);
  } else if (key === "0") {
    setZoom(1, { fitWidth: true });
  }
});

loadSamples().catch((error) => {
  els.subtitle.textContent = `加载失败：${error.message}`;
});
