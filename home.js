"use strict";

const illustrations = [
  "images/home/button-sleep.png",
  "images/home/button-breathe-a.png",
  "images/home/button-breathe-b.png",
  "images/home/button-octopus.png",
  "images/home/button-star.png",
  "images/home/button-sunglasses.png",
  "images/home/button-thumbs-up.png"
];

function shuffledIllustrations() {
  const result = [...illustrations];
  for (let index = result.length - 1; index > 0; index--) {
    const randomIndex = Math.floor(Math.random() * (index + 1));
    [result[index], result[randomIndex]] = [result[randomIndex], result[index]];
  }
  return result;
}

const imageOrder = shuffledIllustrations();
const source = Array.isArray(window.HABANG_LINKS) ? window.HABANG_LINKS : [];
const links = source.flatMap((entry, index) => {
  if (typeof entry?.title !== "string" || typeof entry?.url !== "string") return [];
  let destination;
  try {
    destination = new URL(entry.url, window.location.href);
  } catch {
    return [];
  }
  if (!['http:', 'https:'].includes(destination.protocol)) return [];
  let download = null;
  if (typeof entry.download === "string") {
    try {
      const file = new URL(entry.download, window.location.href);
      if (file.origin === window.location.origin && file.protocol === destination.protocol) download = file.href;
    } catch { /* 잘못된 다운로드 경로는 표시하지 않습니다. */ }
  }
  const tags = Array.isArray(entry.tags)
    ? [...new Set(entry.tags.filter(tag => typeof tag === "string").map(tag => tag.trim().toLowerCase()).filter(Boolean))]
    : [];
  return [{
    title: entry.title.trim(),
    description: typeof entry.description === "string" ? entry.description.trim() : "",
    download,
    downloadLabel: typeof entry.downloadLabel === "string" ? entry.downloadLabel : "설치 파일 받기",
    url: destination.href,
    external: destination.origin !== window.location.origin,
    tags,
    image: imageOrder[index % imageOrder.length]
  }];
}).filter(entry => entry.title);

const searchInput = document.getElementById("link-search");
const filterArea = document.getElementById("tag-filters");
const list = document.getElementById("link-list");
const resultCount = document.getElementById("result-count");
const emptyState = document.getElementById("empty-state");
let selectedTag = "";

const allTags = [...new Set(links.flatMap(link => link.tags))].sort((left, right) => {
  const preferred = ["android", "ai", "photo"];
  const leftRank = preferred.indexOf(left);
  const rightRank = preferred.indexOf(right);
  if (leftRank !== -1 || rightRank !== -1) {
    if (leftRank === -1) return 1;
    if (rightRank === -1) return -1;
    return leftRank - rightRank;
  }
  return left.localeCompare(right);
});

function normalized(value) {
  return value.normalize("NFKC").toLocaleLowerCase().trim();
}

function tagButton(label, value) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "tag-filter";
  button.dataset.tag = value;
  button.textContent = label;
  button.setAttribute("aria-pressed", String(selectedTag === value));
  button.addEventListener("click", () => {
    selectedTag = selectedTag === value ? "" : value;
    render();
  });
  return button;
}

function renderFilters() {
  filterArea.replaceChildren(
    tagButton("전체", ""),
    ...allTags.map(tag => tagButton(`#${tag}`, tag))
  );
}

function createCard(link) {
  const card = document.createElement("article");
  card.className = "link-card";
  const open = document.createElement("a");
  open.className = "card-open";
  open.href = link.url;
  if (link.external) {
    open.target = "_blank";
    open.rel = "noopener noreferrer";
  }

  const artwork = document.createElement("div");
  artwork.className = "card-art";
  const image = document.createElement("img");
  image.src = link.image;
  image.alt = "";
  image.loading = "lazy";
  artwork.append(image);

  const title = document.createElement("h3");
  title.textContent = link.title;

  const tags = document.createElement("div");
  tags.className = "card-tags";
  for (const tag of link.tags) {
    const label = document.createElement("span");
    label.className = "card-tag";
    label.textContent = `#${tag}`;
    tags.append(label);
  }

  if (link.external) open.setAttribute("aria-label", `${link.title}, 새 창에서 열기`);
  open.append(artwork, title);
  card.append(open);
  if (link.description) {
    const description = document.createElement("p");
    description.className = "card-description";
    description.textContent = link.description;
    card.append(description);
  }
  card.append(tags);
  if (link.download) {
    const actions = document.createElement("div");
    actions.className = "card-actions";
    const download = document.createElement("a");
    download.className = "card-download";
    download.href = link.download;
    download.download = "";
    download.textContent = link.downloadLabel;
    download.setAttribute("aria-label", `${link.title}: ${link.downloadLabel}`);
    const guide = document.createElement("a");
    guide.className = "card-guide";
    guide.href = link.url;
    guide.textContent = "설명·설치 방법 →";
    actions.append(download, guide);
    card.append(actions);
  }
  return card;
}

function render() {
  const query = normalized(searchInput.value);
  const visible = links.filter(link => {
    const matchesTag = !selectedTag || link.tags.includes(selectedTag);
    const searchable = normalized([link.title, link.description, ...link.tags].join(" "));
    return matchesTag && (!query || searchable.includes(query));
  });

  for (const button of filterArea.children) {
    button.setAttribute("aria-pressed", String(selectedTag === button.dataset.tag));
  }
  list.replaceChildren(...visible.map(createCard));
  resultCount.textContent = `${visible.length}개의 링크`;
  emptyState.hidden = visible.length !== 0;
}

searchInput.addEventListener("input", render);
renderFilters();
render();
