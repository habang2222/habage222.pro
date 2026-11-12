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
    downloadOnly: entry.downloadOnly === true,
    downloadLabel: typeof entry.downloadLabel === "string" ? entry.downloadLabel : "설치 파일 받기",
    url: destination.href,
    external: destination.origin !== window.location.origin,
    tags,
    image: imageOrder[index % imageOrder.length]
  }];
}).filter(entry => entry.title);

const searchInput = document.getElementById("link-search");
const list = document.getElementById("link-list");
const resultCount = document.getElementById("result-count");
const emptyState = document.getElementById("empty-state");
const navigation = document.getElementById("page-navigation");
const viewport = document.getElementById("card-viewport");
const pageImages = shuffledIllustrations();
const pageSize = 6;
let currentPage = 0;
let matchingLinks = links;

function normalized(value) {
  return value.normalize("NFKC").toLocaleLowerCase().trim();
}

function matchesQuery(link, value) {
  const tokens = normalized(value).split(/\s+/).filter(Boolean);
  const searchable = normalized([link.title, link.description, ...link.tags].join(" "));
  return tokens.every(token => token.startsWith('#')
    ? token.length > 1 && link.tags.some(tag => normalized(tag).includes(token.slice(1)))
    : searchable.includes(token));
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

  if (link.external) open.setAttribute("aria-label", `${link.title}, 새 창에서 열기`);
  open.append(artwork, title);
  card.append(open);
  if (link.description) {
    const description = document.createElement("p");
    description.className = "card-description";
    description.textContent = link.description;
    card.append(description);
  }
  if (link.download) {
    const actions = document.createElement("div");
    actions.className = "card-actions";
    const download = document.createElement("a");
    download.className = "card-download";
    download.href = link.download;
    download.download = "";
    download.textContent = link.downloadLabel;
    download.setAttribute("aria-label", `${link.title}: ${link.downloadLabel}`);
    actions.append(download);
    if (!link.downloadOnly) {
      const guide = document.createElement("a");
      guide.className = "card-guide";
      guide.href = link.url;
      guide.textContent = "설명·설치 방법 →";
      actions.append(guide);
    }
    card.append(actions);
  }
  return card;
}

function changePage(index) {
  currentPage = index;
  render();
  viewport.scrollIntoView({block: 'start', behavior: 'auto'});
  navigation.querySelector('[aria-current="page"]')?.focus({preventScroll: true});
}

function renderNavigation(totalPages) {
  navigation.replaceChildren();
  navigation.hidden = totalPages <= 1;
  if (totalPages <= 1) return;
  const arrow = (text, label, index, disabled) => {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'page-arrow'; button.textContent = text;
    button.setAttribute('aria-label', label); button.disabled = disabled;
    button.addEventListener('click', () => changePage(index));
    return button;
  };
  navigation.append(arrow('←', '이전 프로그램 페이지', currentPage - 1, currentPage === 0));
  for (let index = 0; index < totalPages; index++) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'page-choice';
    button.setAttribute('aria-label', `${index + 1} 페이지`);
    if (index === currentPage) button.setAttribute('aria-current', 'page');
    const image = document.createElement('img');
    image.src = pageImages[index % pageImages.length]; image.alt = ''; image.loading = 'lazy';
    const number = document.createElement('span'); number.textContent = String(index + 1);
    button.append(image, number);
    button.addEventListener('click', () => changePage(index));
    navigation.append(button);
  }
  navigation.append(arrow('→', '다음 프로그램 페이지', currentPage + 1, currentPage === totalPages - 1));
}

function render() {
  matchingLinks = links.filter(link => matchesQuery(link, searchInput.value));
  const totalPages = Math.ceil(matchingLinks.length / pageSize);
  currentPage = Math.max(0, Math.min(currentPage, totalPages - 1));
  list.replaceChildren(...matchingLinks.slice(currentPage * pageSize, (currentPage + 1) * pageSize).map(createCard));
  resultCount.textContent = `${matchingLinks.length}개 프로그램${totalPages ? ` · ${currentPage + 1} / ${totalPages} 페이지` : ''}`;
  emptyState.hidden = matchingLinks.length !== 0;
  renderNavigation(totalPages);
}

let touchStart = null;
viewport.addEventListener('touchstart', event => {
  if (event.touches.length === 1) touchStart = [event.touches[0].clientX, event.touches[0].clientY];
}, {passive: true});
viewport.addEventListener('touchend', event => {
  if (!touchStart || !event.changedTouches.length) return;
  const dx = event.changedTouches[0].clientX - touchStart[0];
  const dy = event.changedTouches[0].clientY - touchStart[1];
  touchStart = null;
  if (Math.abs(dx) < 70 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
  const next = currentPage + (dx < 0 ? 1 : -1);
  if (next >= 0 && next < Math.ceil(matchingLinks.length / pageSize)) changePage(next);
}, {passive: true});
viewport.addEventListener('touchcancel', () => { touchStart = null; }, {passive: true});
searchInput.addEventListener("input", () => { currentPage = 0; render(); });
render();
