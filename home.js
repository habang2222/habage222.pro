"use strict";

const illustrations = [
  "images/home/button-sleep.png",
  "images/home/button-breathe-a.png",
  "images/home/button-breathe-b.png",
  "images/home/button-octopus.png"
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
  const tags = Array.isArray(entry.tags)
    ? [...new Set(entry.tags.filter(tag => typeof tag === "string").map(tag => tag.trim().toLowerCase()).filter(Boolean))]
    : [];
  return [{
    title: entry.title.trim(),
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
  const card = document.createElement("a");
  card.className = "link-card";
  card.href = link.url;
  if (link.external) {
    card.target = "_blank";
    card.rel = "noopener noreferrer";
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

  const open = document.createElement("span");
  open.className = "card-open";
  const openLabel = document.createElement("span");
  openLabel.textContent = link.external ? "새 창에서 열기" : "열기";
  const arrow = document.createElement("span");
  arrow.setAttribute("aria-hidden", "true");
  arrow.textContent = "↗";
  open.append(openLabel, arrow);

  card.append(artwork, title, tags, open);
  return card;
}

function render() {
  const query = normalized(searchInput.value);
  const visible = links.filter(link => {
    const matchesTag = !selectedTag || link.tags.includes(selectedTag);
    const searchable = normalized([link.title, ...link.tags].join(" "));
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
