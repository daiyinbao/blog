/* ═══════════════════════════════════════════════════════════
   主题交互脚本（原生 JS，无依赖）
   ═══════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  // 由 Hugo 在构建时注入（兼容 GitHub Pages 子路径部署）
  var SEARCH_INDEX_URL = "{{ `index.json` | relURL }}";

  document.addEventListener("DOMContentLoaded", function () {
    initTheme();
    initSidebarToggle();
    initMobileNav();
    initTreeToggle();
    highlightActiveArticle();
    initHoverPreview();
    initCodeCopy();
    initImageLightbox();
    initTocScrollSpy();
    initSearch();
  });

  /* ── 主题切换 ───────────────────────────────────────────── */
  function initTheme() {
    var checkbox = document.getElementById("checkbox");
    var root = document.documentElement;
    if (!checkbox) return;

    checkbox.checked = root.getAttribute("data-theme") === "dark";

    checkbox.addEventListener("change", function () {
      var theme = checkbox.checked ? "dark" : "light";
      root.setAttribute("data-theme", theme);
      localStorage.setItem("theme", theme);
    });
  }

  /* ── 整棵目录树的收起 / 展开 ─────────────────────────────── */
  function initSidebarToggle() {
    var button = document.getElementById("sidebar-toggle");
    if (!button) return;

    var root = document.documentElement;

    function sync() {
      var collapsed = root.classList.contains("sidebar-collapsed");
      button.setAttribute("aria-expanded", String(!collapsed));
      button.title = collapsed ? "展开目录树" : "收起目录树";
    }

    sync();

    button.addEventListener("click", function () {
      var collapsed = root.classList.toggle("sidebar-collapsed");
      localStorage.setItem("sidebar", collapsed ? "collapsed" : "expanded");
      sync();
    });
  }

  /* ── 移动端：目录抽屉 ───────────────────────────────────── */
  function initMobileNav() {
    var button = document.getElementById("mobile-menu-btn");
    var sidebar = document.getElementById("sidebar-left");
    var backdrop = document.getElementById("sidebar-backdrop");
    if (!button || !sidebar || !backdrop) return;

    var root = document.documentElement;

    function setOpen(open) {
      root.classList.toggle("mobile-nav-open", open);
      button.setAttribute("aria-expanded", String(open));
    }

    button.addEventListener("click", function () {
      setOpen(!root.classList.contains("mobile-nav-open"));
    });

    backdrop.addEventListener("click", function () { setOpen(false); });

    // 点击目录里的文章链接后自动收起（栏目是 span，不受影响）
    sidebar.addEventListener("click", function (event) {
      if (event.target.closest("a")) setOpen(false);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && root.classList.contains("mobile-nav-open")) {
        setOpen(false);
      }
    });

    // 视口变宽（回到桌面布局）时复位，避免状态残留
    window.addEventListener("resize", function () {
      if (window.innerWidth > 768) setOpen(false);
    });
  }

  /* ── 文档树折叠 ─────────────────────────────────────────── */
  function initTreeToggle() {
    document.addEventListener("click", function (event) {
      var trigger = event.target.closest(".tree-toggle");
      var link = event.target.closest(".section-link");
      var target = trigger || link;
      if (!target) return;

      var item = target.closest("li");
      if (!item) return;

      var children = null;
      var icon = null;
      for (var i = 0; i < item.children.length; i++) {
        var child = item.children[i];
        if (child.classList.contains("tree-children")) children = child;
        if (child.classList.contains("tree-toggle")) icon = child;
      }
      if (!children || !icon) return;

      event.preventDefault();
      event.stopPropagation();

      if (children.classList.contains("hidden")) {
        children.classList.remove("hidden");
        children.style.display = "block";
        icon.classList.remove("collapsed");
        icon.classList.add("expanded");
      } else {
        children.classList.add("hidden");
        children.style.display = "none";
        icon.classList.remove("expanded");
        icon.classList.add("collapsed");
      }
    });
  }

  /* ── 高亮当前文章并展开其所在栏目 ───────────────────────── */
  function normalize(path) {
    return path.replace(/\/+$/, "");
  }

  function highlightActiveArticle() {
    var here = normalize(window.location.pathname);

    document.querySelectorAll(".tree a").forEach(function (a) {
      var href = a.getAttribute("href");
      if (!href) return;
      if (normalize(href) !== here) return;

      a.classList.add("active");
      a.style.fontWeight = "bold";
      a.style.color = "var(--link-color)";

      var item = a.closest("li");
      if (item) item.classList.add("tree-active");

      var block = a.closest(".tree-children");
      while (block) {
        block.classList.remove("hidden");
        block.style.display = "block";
        var parentItem = block.parentElement;
        var icon = parentItem ? parentItem.querySelector(".tree-toggle") : null;
        if (icon) {
          icon.classList.remove("collapsed");
          icon.classList.add("expanded");
        }
        block = parentItem ? parentItem.closest(".tree-children") : null;
      }
    });
  }

  /* ── 首页文章悬停预览 ───────────────────────────────────── */
  function initHoverPreview() {
    var links = document.querySelectorAll(".homepage-tree .article-link");
    if (!links.length) return;

    var tooltip = document.createElement("div");
    tooltip.className = "preview-tooltip";
    document.body.appendChild(tooltip);

    var timer = null;

    links.forEach(function (link) {
      link.addEventListener("mouseenter", function (event) {
        if (window.innerWidth <= 768) return;
        var summary = link.getAttribute("data-summary");
        if (!summary) return;

        var x = event.clientX;
        var y = event.clientY;

        timer = setTimeout(function () {
          tooltip.textContent = summary.length > 200 ? summary.slice(0, 200) + "..." : summary;
          tooltip.style.display = "block";

          var left = x + 15;
          var top = y + 15;
          var width = 500;
          if (left + width > window.innerWidth) left = x - width - 15;
          if (top + 150 > window.innerHeight) top = y - 140;

          tooltip.style.left = left + "px";
          tooltip.style.top = top + "px";
        }, 450);
      });

      link.addEventListener("mouseleave", function () {
        clearTimeout(timer);
        tooltip.style.display = "none";
      });
    });
  }

  /* ── 代码块：套上窗口 + 复制按钮 ────────────────────────── */
  function initCodeCopy() {
    document.querySelectorAll(".markdown-body pre").forEach(function (pre) {
      if (pre.closest(".code-wrapper")) return;

      var wrapper = document.createElement("div");
      wrapper.className = "code-wrapper";
      pre.parentNode.insertBefore(wrapper, pre);
      wrapper.appendChild(pre);

      var button = document.createElement("button");
      button.className = "copy-btn";
      button.type = "button";
      button.textContent = "Copy";
      button.addEventListener("click", function () {
        var code = pre.querySelector("code");
        var text = code ? code.innerText : pre.innerText;
        navigator.clipboard.writeText(text).then(function () {
          button.textContent = "Copied!";
          setTimeout(function () {
            button.textContent = "Copy";
          }, 2000);
        }).catch(function () {
          button.textContent = "Error";
        });
      });
      wrapper.appendChild(button);
    });
  }

  /* ── 点击图片放大（多图时支持上一张 / 下一张） ───────────── */
  function initImageLightbox() {
    // 图片本身是链接的跳过，保留原有跳转行为
    var images = Array.prototype.filter.call(
      document.querySelectorAll(".markdown-body img"),
      function (img) { return !img.closest("a"); }
    );
    if (!images.length) return;

    var multi = images.length > 1;

    var box = document.createElement("div");
    box.className = "lightbox" + (multi ? "" : " lightbox-single");
    box.innerHTML = [
      '<button class="lightbox-close" type="button" aria-label="关闭">&times;</button>',
      '<button class="lightbox-nav lightbox-prev" type="button" aria-label="上一张">',
      '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>',
      "</button>",
      '<img alt="">',
      '<button class="lightbox-nav lightbox-next" type="button" aria-label="下一张">',
      '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>',
      "</button>",
      '<span class="lightbox-counter"></span>',
      '<span class="lightbox-hint"></span>'
    ].join("");
    document.body.appendChild(box);

    var bigImg = box.querySelector("img");
    var closeBtn = box.querySelector(".lightbox-close");
    var prevBtn = box.querySelector(".lightbox-prev");
    var nextBtn = box.querySelector(".lightbox-next");
    var counter = box.querySelector(".lightbox-counter");
    var hint = box.querySelector(".lightbox-hint");
    var index = 0;

    hint.textContent = multi
      ? "← → 切换 · 点击图片或按 Esc 关闭"
      : "点击图片或按 Esc 关闭";

    // 循环切换，第 index 张
    function show(i) {
      index = (i + images.length) % images.length;
      var img = images[index];
      bigImg.src = img.currentSrc || img.src;
      bigImg.alt = img.alt || "";
      if (multi) counter.textContent = (index + 1) + " / " + images.length;
    }

    function open(i) {
      show(i);
      box.classList.add("open");
      document.body.style.overflow = "hidden";
    }

    function close() {
      box.classList.remove("open");
      document.body.style.overflow = "";
      setTimeout(function () {
        if (!box.classList.contains("open")) bigImg.removeAttribute("src");
      }, 250);
    }

    images.forEach(function (img, i) {
      img.setAttribute("tabindex", "0");
      img.setAttribute("role", "button");
      img.style.cursor = "zoom-in";

      img.addEventListener("click", function () { open(i); });
      img.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open(i);
        }
      });
    });

    prevBtn.addEventListener("click", function () { show(index - 1); });
    nextBtn.addEventListener("click", function () { show(index + 1); });

    box.addEventListener("click", function (e) {
      if (e.target === box || e.target === bigImg || e.target === closeBtn) close();
    });

    document.addEventListener("keydown", function (e) {
      if (!box.classList.contains("open")) return;
      if (e.key === "Escape") close();
      else if (multi && e.key === "ArrowLeft") show(index - 1);
      else if (multi && e.key === "ArrowRight") show(index + 1);
    });

    // 移动端左右滑动切换
    var startX = null;
    box.addEventListener("touchstart", function (e) {
      startX = e.touches.length === 1 ? e.touches[0].clientX : null;
    }, { passive: true });
    box.addEventListener("touchend", function (e) {
      if (startX === null || !multi) { startX = null; return; }
      var dx = e.changedTouches[0].clientX - startX;
      startX = null;
      if (Math.abs(dx) > 50) show(index + (dx < 0 ? 1 : -1));
    }, { passive: true });
  }

  /* ── 大纲滚动高亮 ───────────────────────────────────────── */
  function initTocScrollSpy() {
    var links = document.querySelectorAll("#TableOfContents a");
    if (!links.length) return;

    var headings = [];
    links.forEach(function (link) {
      var id = decodeURIComponent(link.getAttribute("href").slice(1));
      var el = document.getElementById(id);
      if (el) headings.push(el);
    });
    if (!headings.length) return;

    var sidebar = document.querySelector(".sidebar-right");

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;

        links.forEach(function (l) { l.classList.remove("active"); });

        var active = document.querySelector('#TableOfContents a[href="#' + entry.target.id + '"]');
        if (!active) return;
        active.classList.add("active");

        if (sidebar) {
          var rect = active.getBoundingClientRect();
          var box = sidebar.getBoundingClientRect();
          if (rect.top < box.top || rect.bottom > box.bottom) {
            sidebar.scrollTo({
              top: active.offsetTop - sidebar.clientHeight / 2 + active.clientHeight / 2,
              behavior: "smooth"
            });
          }
        }
      });
    }, { root: null, rootMargin: "0px 0px -80% 0px", threshold: 0 });

    headings.forEach(function (h) { observer.observe(h); });
  }

  /* ── 全文搜索 ───────────────────────────────────────────── */
  function initSearch() {
    var trigger = document.getElementById("search-trigger");
    var modal = document.getElementById("search-modal");
    var input = document.getElementById("search-input");
    var results = document.getElementById("search-results");
    var loading = document.querySelector(".search-loading");
    if (!modal || !input || !results) return;

    var index = null;
    var selected = -1;

    function open(event) {
      var content = document.querySelector(".search-modal-content");
      if (content) {
        if (event && event.type === "click" && event.currentTarget) {
          var r = event.currentTarget.getBoundingClientRect();
          var cx = r.left + r.width / 2;
          var cy = r.top + r.height / 2;
          var width = Math.min(600, window.innerWidth * 0.9);
          var left = (window.innerWidth - width) / 2;
          var top = window.innerHeight * 0.15;
          content.style.transformOrigin = (cx - left) + "px " + (cy - top) + "px";
        } else {
          content.style.transformOrigin = "center top";
        }
      }
      modal.classList.add("open");
      input.focus();
      if (!index) loadIndex();
    }

    function close() {
      modal.classList.add("closing");
      modal.classList.remove("open");
      setTimeout(function () {
        modal.classList.remove("closing");
        input.value = "";
        results.innerHTML = "";
        selected = -1;
      }, 200);
    }

    function loadIndex() {
      if (loading) loading.style.display = "block";
      fetch(SEARCH_INDEX_URL + "?t=" + Date.now())
        .then(function (r) { return r.json(); })
        .then(function (data) { index = data; })
        .catch(function (err) {
          console.error("搜索索引加载失败：", err);
          results.innerHTML = '<div class="search-empty">搜索索引加载失败</div>';
        })
        .finally(function () { if (loading) loading.style.display = "none"; });
    }

    function render(items) {
      if (!items.length) {
        results.innerHTML = '<div class="search-empty">没有找到相关文章</div>';
        return;
      }
      results.innerHTML = items.map(function (item, i) {
        var title = escapeHtml(item.title || "");
        var excerpt = escapeHtml(item.summary || "暂无摘要");
        return '<div class="search-result-item" data-index="' + i + '">' +
          '<span class="search-result-title">' + title + "</span>" +
          '<span class="search-result-excerpt">' + excerpt + "</span>" +
          "</div>";
      }).join("");

      results.querySelectorAll(".search-result-item").forEach(function (el) {
        el.addEventListener("click", function () {
          window.location.href = items[Number(el.dataset.index)].link;
        });
      });
      selected = -1;
    }

    function escapeHtml(str) {
      return String(str).replace(/[&<>"']/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
      });
    }

    function move(step) {
      var items = results.querySelectorAll(".search-result-item");
      if (!items.length) return;
      selected = (selected + step + items.length) % items.length;
      items.forEach(function (el, i) {
        el.classList.toggle("selected", i === selected);
      });
      items[selected].scrollIntoView({ block: "nearest" });
    }

    if (trigger) trigger.addEventListener("click", open);
    var mobileTrigger = document.getElementById("mobile-search-trigger");
    if (mobileTrigger) mobileTrigger.addEventListener("click", open);
    var exitBtn = document.getElementById("mobile-exit-btn");
    if (exitBtn) exitBtn.addEventListener("click", close);
    var submitBtn = document.getElementById("mobile-search-btn");
    if (submitBtn) submitBtn.addEventListener("click", function () {
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.blur();
    });

    modal.addEventListener("click", function (e) {
      if (e.target === modal) close();
    });

    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (modal.classList.contains("open")) close(); else open();
        return;
      }
      if (!modal.classList.contains("open")) return;
      if (e.key === "Escape") close();
    });

    input.addEventListener("input", function () {
      var query = input.value.toLowerCase().trim();
      if (!query) {
        results.innerHTML = "";
        selected = -1;
        return;
      }
      if (!index) return;
      var matched = index.filter(function (item) {
        var inTitle = item.title && item.title.toLowerCase().indexOf(query) !== -1;
        var inContent = item.content && item.content.toLowerCase().indexOf(query) !== -1;
        return inTitle || inContent;
      }).slice(0, 50);
      render(matched);
    });

    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (e.key === "Enter") {
        e.preventDefault();
        var items = results.querySelectorAll(".search-result-item");
        if (selected >= 0 && items[selected]) items[selected].click();
        else if (items.length) items[0].click();
      }
    });
  }
})();
