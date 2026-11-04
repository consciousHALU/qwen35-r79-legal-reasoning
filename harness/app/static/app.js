/* ============================================================
   行政复议智能助手 —— 前端逻辑(原生 JS,无任何外部依赖)
   后端基址:同源(端口 8090),接口见 harness/SPEC.md
   ============================================================ */
(function () {
  "use strict";

  /* ---------- 常量 ---------- */
  var SHORT_TIMEOUT = 15000;    // 状态 / 示例案件
  var LONG_TIMEOUT = 600000;    // 推理类请求:真实模型可能数分钟,给到 10 分钟
  var STATUS_INTERVAL = 30000;  // 状态徽标 30s 轮询

  var STATUS_LABEL = {
    proved: "已证实",
    asserted: "当事人主张",
    contradicted: "存在矛盾",
    unknown: "无法确认"
  };

  var DATE_STATUS_LABEL = {
    exact: "日期确切",
    partial: "日期部分确定",
    unknown: "日期待定"
  };

  /* ---------- 工具函数 ---------- */
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /* 把文书 markdown 渲染为正式文书版式(# 标题居中,## 节标题,### 小节,其余为首行缩进段落) */
  function renderDocHtml(md) {
    var lines = String(md || "").split(/\r?\n/);
    var html = "";
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var t = line.trim();
      if (!t) { continue; }
      if (t.indexOf("### ") === 0) {
        html += '<h4 class="doc-h3">' + escapeHtml(t.slice(4)) + "</h4>";
      } else if (t.indexOf("## ") === 0) {
        html += '<h3 class="doc-h2">' + escapeHtml(t.slice(3)) + "</h3>";
      } else if (t.indexOf("# ") === 0) {
        html += '<div class="doc-title">' + escapeHtml(t.slice(2)) + "</div>";
      } else {
        html += '<p class="doc-p">' + escapeHtml(t) + "</p>";
      }
    }
    return html;
  }

  function abbrev(s, n) {
    s = String(s == null ? "" : s);
    return s.length > n ? s.slice(0, n) + "…" : s;
  }

  function statusTag(status) {
    var st = STATUS_LABEL.hasOwnProperty(status) ? status : "unknown";
    return '<span class="status-tag st-tag-' + st + '">' + STATUS_LABEL[st] + "</span>";
  }

  function refPills(refs) {
    if (!refs || !refs.length) return "";
    var html = '<div class="refs">';
    for (var i = 0; i < refs.length; i++) {
      html += '<span class="ref-pill">' + escapeHtml(refs[i]) + "</span>";
    }
    return html + "</div>";
  }

  /* fetch 封装:超时中断 + resp.ok 检查 + detail 提取 */
  function apiFetch(url, options, timeoutMs) {
    options = options || {};
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, timeoutMs || SHORT_TIMEOUT);
    options.signal = controller.signal;
    return fetch(url, options).then(function (resp) {
      return resp.json().catch(function () { return null; }).then(function (data) {
        if (!resp.ok) {
          var detail = (data && data.detail) ? data.detail : ("请求失败(HTTP " + resp.status + ")");
          throw new Error(detail);
        }
        return data;
      });
    }).catch(function (err) {
      if (err && err.name === "AbortError") {
        throw new Error("请求超时:模型推理耗时过长或服务无响应,请稍后重试");
      }
      if (err instanceof TypeError) {
        throw new Error("无法连接后端服务,请确认 harness 已启动(默认端口 8090)");
      }
      throw err;
    }).finally(function () {
      clearTimeout(timer);
    });
  }

  /* Blob 下载 */
  function downloadBlob(content, filename, mime) {
    var blob = new Blob([content], { type: mime });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(function () {
      URL.revokeObjectURL(url);
      a.remove();
    }, 200);
  }

  /* 复制全文(含降级方案) */
  function copyText(text, btn) {
    function done() {
      var old = btn.textContent;
      btn.textContent = "已复制";
      setTimeout(function () { btn.textContent = old; }, 1500);
    }
    function fallback() {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        done();
      } catch (e) {
        alert("复制失败,请手动选择文本复制");
      }
      ta.remove();
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(fallback);
    } else {
      fallback();
    }
  }

  /* 提交任务:按钮置灰 + 加载动画 + 已用秒数 + 失败红色错误条 */
  function runTask(btn, resultEl, taskFn) {
    btn.disabled = true;
    var start = Date.now();
    resultEl.innerHTML =
      '<div class="loading-box">' +
        '<div class="spinner"></div>' +
        '<div class="loading-text">本地推理中,可能需要 1-5 分钟,请耐心等待</div>' +
        '<div class="loading-elapsed">已用 <span class="elapsed">0</span> 秒</div>' +
      "</div>";
    var elapsedEl = resultEl.querySelector(".elapsed");
    var timer = setInterval(function () {
      if (elapsedEl) {
        elapsedEl.textContent = String(Math.floor((Date.now() - start) / 1000));
      }
    }, 1000);
    return taskFn().catch(function (err) {
      resultEl.innerHTML =
        '<div class="error-bar">请求失败:' + escapeHtml((err && err.message) || String(err)) + "</div>";
    }).finally(function () {
      clearInterval(timer);
      btn.disabled = false;
    });
  }

  /* ============================================================
     后端状态徽标(30 秒轮询 GET /api/status)
     mock=true → 黄「演示模式」;reachable/ok → 绿「已连接模型服务」;否则红「未连接」
     ============================================================ */
  var statusBadge = document.getElementById("status-badge");
  var statusText = document.getElementById("status-text");

  function setStatus(cls, text) {
    statusBadge.className = "status-badge " + cls;
    statusText.textContent = text;
  }

  function refreshStatus() {
    return apiFetch("/api/status", {}, SHORT_TIMEOUT).then(function (data) {
      var backend = data ? data.backend : null;
      if (data && data.mock === true) {
        setStatus("st-mock", "演示模式");
      } else if (backend && backend.reachable === false) {
        setStatus("st-down", "未连接");
      } else if (backend && backend.error) {
        setStatus("st-down", "未连接");
      } else if (backend && (backend.reachable === true || backend.status === "ok" || backend.status)) {
        setStatus("st-ok", "已连接模型服务");
      } else {
        setStatus("st-down", "未连接");
      }
    }).catch(function () {
      setStatus("st-down", "未连接");
    });
  }

  refreshStatus();
  setInterval(refreshStatus, STATUS_INTERVAL);

  /* ============================================================
     标签页切换(不刷新页面)
     ============================================================ */
  var tabBtns = document.querySelectorAll(".tab-btn");
  for (var t = 0; t < tabBtns.length; t++) {
    (function (btn) {
      btn.addEventListener("click", function () {
        for (var i = 0; i < tabBtns.length; i++) {
          tabBtns[i].classList.toggle("active", tabBtns[i] === btn);
        }
        var panels = document.querySelectorAll(".tab-panel");
        for (var j = 0; j < panels.length; j++) {
          panels[j].classList.toggle("active", panels[j].id === "panel-" + btn.getAttribute("data-tab"));
        }
      });
    })(tabBtns[t]);
  }

  /* ============================================================
     共享组件:案件材料编辑器
     每页实例化一个;opts.onLoadSample(data) 用于填充该页其他默认字段
     ============================================================ */
  function createMaterialsEditor(mountEl, opts) {
    opts = opts || {};
    mountEl.innerHTML =
      '<div class="materials-header"><h2>案件材料</h2>' +
      '<p class="materials-sub">支持决定书、送达回证、陈述申辩书、证据材料等文本。</p></div>' +
      '<div class="materials-list"></div>' +
      '<div class="materials-actions">' +
        '<button type="button" class="btn btn-sm act-add">+ 添加材料</button>' +
        '<button type="button" class="btn btn-sm act-import">从文件导入(.txt/.md)</button>' +
        '<input type="file" class="file-input" accept=".txt,.md" multiple style="display:none">' +
        '<button type="button" class="btn btn-sm act-sample">载入示例案件</button>' +
      "</div>";

    var listEl = mountEl.querySelector(".materials-list");
    var fileInput = mountEl.querySelector(".file-input");

    function refreshEmptyHint() {
      var hint = listEl.querySelector(".materials-empty");
      var hasCards = !!listEl.querySelector(".material-card");
      if (!hasCards && !hint) {
        var div = document.createElement("div");
        div.className = "materials-empty";
        div.textContent = "尚未添加案件材料";
        listEl.appendChild(div);
      } else if (hasCards && hint) {
        hint.remove();
      }
    }

    function addCard(title, text) {
      var card = document.createElement("div");
      card.className = "material-card";
      card.innerHTML =
        '<div class="material-card-head">' +
          '<input type="text" class="mat-title" placeholder="材料标题">' +
          '<button type="button" class="btn-del" title="删除该材料">删除</button>' +
        "</div>" +
        '<textarea class="mat-text" placeholder="粘贴材料正文…"></textarea>';
      card.querySelector(".mat-title").value = title || "";
      card.querySelector(".mat-text").value = text || "";
      card.querySelector(".btn-del").addEventListener("click", function () {
        card.remove();
        refreshEmptyHint();
      });
      listEl.appendChild(card);
      refreshEmptyHint();
      return card;
    }

    mountEl.querySelector(".act-add").addEventListener("click", function () {
      addCard("", "");
    });

    mountEl.querySelector(".act-import").addEventListener("click", function () {
      fileInput.click();
    });

    fileInput.addEventListener("change", function () {
      var files = Array.prototype.slice.call(fileInput.files || []);
      files.forEach(function (f) {
        var reader = new FileReader();
        reader.onload = function () {
          addCard(f.name, String(reader.result || ""));
        };
        reader.onerror = function () {
          alert("文件读取失败:" + f.name);
        };
        reader.readAsText(f);
      });
      fileInput.value = "";
    });

    mountEl.querySelector(".act-sample").addEventListener("click", function () {
      apiFetch("/api/sample-case", {}, SHORT_TIMEOUT).then(function (data) {
        listEl.innerHTML = "";
        var mats = (data && data.materials) || [];
        for (var i = 0; i < mats.length; i++) {
          addCard(mats[i].title, mats[i].text);
        }
        refreshEmptyHint();
        if (opts.onLoadSample) opts.onLoadSample(data || {});
      }).catch(function (err) {
        alert("载入示例案件失败:" + ((err && err.message) || err));
      });
    });

    refreshEmptyHint();

    return {
      addCard: addCard,
      /* 返回正文非空的材料;标题缺省补「未命名材料」 */
      getMaterials: function () {
        var cards = listEl.querySelectorAll(".material-card");
        var out = [];
        for (var i = 0; i < cards.length; i++) {
          var title = cards[i].querySelector(".mat-title").value.trim();
          var text = cards[i].querySelector(".mat-text").value;
          if (text.trim() !== "") {
            out.push({ title: title || "未命名材料", text: text });
          }
        }
        return out;
      }
    };
  }

  /* 材料为空 → 前端直接提示并中止 */
  function collectMaterials(editor) {
    var mats = editor.getMaterials();
    if (!mats.length) {
      alert("请至少添加一份案件材料");
      return null;
    }
    return mats;
  }

  /* ============================================================
     ① 案件咨询
     ============================================================ */
  var consultEditor = createMaterialsEditor(document.getElementById("consult-materials"), {
    onLoadSample: function (data) {
      if (typeof data.question === "string") {
        document.getElementById("consult-question").value = data.question;
      }
    }
  });

  function renderConsult(data, resultEl, searchWiki) {
    var assist = (data && data.assist) || {};
    var answer = assist.answer || {};
    var meta = (data && data.meta) || {};
    var routing = meta.routing || {};
    var html = "";

    /* 审计信息条 */
    html += '<div class="audit-bar">' +
      "<span>workflow_id:<b>" + escapeHtml(meta.workflow_id || "—") + "</b></span>" +
      "<span>后端生成请求数:<b>" + escapeHtml(meta.backend_generation_requests != null ? meta.backend_generation_requests : "—") + "</b></span>" +
      "<span>路由:<b>facts=" + escapeHtml(routing.facts || "—") +
      " · procedure=" + escapeHtml(routing.procedure || "—") +
      " · final=" + escapeHtml(routing["final"] || "—") + "</b></span>" +
      "</div>";

    if (assist.mock_notice) {
      html += '<div class="mock-notice">' + escapeHtml(assist.mock_notice) + "</div>";
    }

    /* 结论卡 */
    html += '<div class="card conclusion-card"><h2>结论</h2>' +
      '<p class="conclusion-text">' + escapeHtml(answer.conclusion || "(无结论)") + "</p></div>";

    /* 分析(保留换行) */
    if (answer.analysis) {
      html += '<div class="card"><h2>分析</h2>' +
        '<div class="analysis-text">' + escapeHtml(answer.analysis) + "</div></div>";
    }

    /* 主张列表 */
    var claims = answer.claims || [];
    html += '<div class="card"><h2>主张与依据(' + claims.length + ")</h2>";
    if (!claims.length) {
      html += '<p class="muted">无。</p>';
    }
    for (var i = 0; i < claims.length; i++) {
      var c = claims[i];
      var st = STATUS_LABEL.hasOwnProperty(c.evidence_status) ? c.evidence_status : "unknown";
      html += '<div class="claim-card esb-' + st + '">' +
        statusTag(st) +
        "<p>" + escapeHtml(c.claim) + "</p>" +
        refPills(c.source_refs) +
        "</div>";
    }
    html += "</div>";

    /* 局限清单 */
    var limitations = answer.limitations || [];
    if (limitations.length) {
      html += '<div class="card"><h2>局限与提示</h2><ul class="plain-list">';
      for (var j = 0; j < limitations.length; j++) {
        html += "<li>" + escapeHtml(limitations[j]) + "</li>";
      }
      html += "</ul></div>";
    }

    /* 类案参考卡(仅在勾选检索时展示) */
    if (searchWiki) {
      var wiki = data ? data.wiki : null;
      var result = wiki && wiki.result;
      if (result) {
        html += '<div class="card wiki-card"><h2>类案参考</h2>' +
          '<div class="wiki-title">' + escapeHtml(result.source_id || "—") +
          (result.title ? " · " + escapeHtml(result.title) : "") + "</div>" +
          '<div class="wiki-original">' + escapeHtml(result.full_original || "") + "</div>" +
          '<div class="wiki-note">检索仅返回原文,未参与推理</div>' +
          "</div>";
      } else {
        html += '<div class="card wiki-card"><h2>类案参考</h2>' +
          '<p class="muted">未检索到相关类案</p></div>';
      }
    }

    resultEl.innerHTML = html;
  }

  document.getElementById("consult-submit").addEventListener("click", function () {
    var question = document.getElementById("consult-question").value.trim();
    if (!question) {
      alert("请输入咨询问题");
      return;
    }
    var materials = collectMaterials(consultEditor);
    if (!materials) return;
    var searchWiki = document.getElementById("consult-wiki").checked;
    var btn = this;
    var resultEl = document.getElementById("consult-result");
    runTask(btn, resultEl, function () {
      return apiFetch("/api/consult", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question, materials: materials, search_wiki: searchWiki })
      }, LONG_TIMEOUT).then(function (data) {
        renderConsult(data, resultEl, searchWiki);
      });
    });
  });

  /* ============================================================
     ② 证据链梳理
     ============================================================ */
  var evEditor = createMaterialsEditor(document.getElementById("ev-materials"), {});

  function statBlock(label, num, extraCls) {
    return '<div class="stat-block' + (extraCls ? " " + extraCls : "") + '">' +
      '<div class="stat-num">' + escapeHtml(num != null ? num : "—") + "</div>" +
      '<div class="stat-label">' + escapeHtml(label) + "</div></div>";
  }

  function renderEvidenceChain(data, resultEl) {
    var chain = (data && data.chain) || {};
    var stats = chain.stats || {};
    var timeline = chain.timeline || [];
    var evidenceList = chain.evidence || [];
    var matrix = chain.matrix || { event_ids: [], evidence_ids: [], cells: [] };
    var actors = chain.actors || [];
    var steps = chain.procedure_steps || [];
    var deadlines = chain.deadlines || [];
    var uncertainties = chain.uncertainties || [];

    var html = "";

    /* 顶部导出按钮 */
    html += '<div class="result-toolbar">' +
      '<button type="button" class="btn" id="ev-export">导出梳理报告(.md)</button></div>';

    /* 统计色块行 */
    html += '<div class="stats-row">' +
      statBlock("主体", stats.actors) +
      statBlock("事件", stats.events) +
      statBlock("证据", stats.evidence) +
      statBlock("待核实", stats.uncertainties, "warn") +
      statBlock("矛盾", stats.contradicted, "danger") +
      "</div>";

    /* 事件时间轴 */
    html += '<div class="card"><h2>事件时间轴(' + timeline.length + ")</h2>";
    if (!timeline.length) {
      html += '<p class="muted">未识别出事件。</p>';
    } else {
      html += '<div class="timeline">';
      for (var i = 0; i < timeline.length; i++) {
        var ev = timeline[i];
        var ds = (ev.date_status === "exact" || ev.date_status === "partial") ? ev.date_status : "unknown";
        var es = STATUS_LABEL.hasOwnProperty(ev.evidence_status) ? ev.evidence_status : "unknown";
        var dateHtml = (ds === "unknown")
          ? '<span class="tl-date ds-unknown">日期待定</span>'
          : '<span class="tl-date ds-' + ds + '">' + escapeHtml(ev.date_text || "日期待定") + "</span>";
        html += '<div class="tl-item">' +
          '<div class="tl-left">' + dateHtml + "</div>" +
          '<div class="tl-rail"><div class="tl-node es-' + es + " ds-" + ds +
            '" title="证据状态:' + escapeHtml(STATUS_LABEL[es]) + ";日期状态:" +
            escapeHtml(DATE_STATUS_LABEL[ds] || ds) + '"></div></div>' +
          '<div class="tl-content">' +
            '<div class="tl-head"><span class="tl-id">' + escapeHtml(ev.event_id || "") + "</span>" +
              statusTag(es) + "</div>" +
            '<div class="tl-action">' + escapeHtml(ev.action || "") + "</div>";
        var metaBits = [];
        if (ev.object) metaBits.push("对象:" + ev.object);
        if (ev.actor_names && ev.actor_names.length) metaBits.push("主体:" + ev.actor_names.join("、"));
        if (metaBits.length) {
          html += '<div class="tl-meta">' + escapeHtml(metaBits.join(" · ")) + "</div>";
        }
        html += refPills(ev.source_refs) + "</div></div>";
      }
      html += "</div>";
    }
    html += "</div>";

    /* 证据×事件支持矩阵 */
    var evDesc = {};
    for (var e = 0; e < evidenceList.length; e++) {
      evDesc[evidenceList[e].evidence_id] = evidenceList[e].description || "";
    }
    var evAction = {};
    for (var a = 0; a < timeline.length; a++) {
      evAction[timeline[a].event_id] = timeline[a].action || "";
    }
    var evIds = matrix.evidence_ids || [];
    var eventIds = matrix.event_ids || [];
    var cells = matrix.cells || [];
    html += '<div class="card"><h2>证据 × 事件支持矩阵</h2>';
    if (!evIds.length || !eventIds.length) {
      html += '<p class="muted">暂无可展示的支持关系。</p>';
    } else {
      html += '<div class="matrix-wrap"><table class="matrix"><thead><tr>' +
        '<th class="mx-corner">事件 \\ 证据</th>';
      for (var c2 = 0; c2 < evIds.length; c2++) {
        html += '<th title="' + escapeHtml(evDesc[evIds[c2]] || "") + '">' + escapeHtml(evIds[c2]) + "</th>";
      }
      html += "</tr></thead><tbody>";
      for (var r = 0; r < eventIds.length; r++) {
        var eid = eventIds[r];
        html += '<tr><th class="mx-event" title="' + escapeHtml(evAction[eid] || "") + '">' +
          escapeHtml(abbrev(evAction[eid] || "(无描述)", 12)) +
          '<span class="mx-id">' + escapeHtml(eid) + "</span></th>";
        for (var c3 = 0; c3 < evIds.length; c3++) {
          var hit = !!(cells[r] && cells[r][c3]);
          html += '<td class="' + (hit ? "mx-hit" : "") + '" title="' +
            escapeHtml(evDesc[evIds[c3]] || "") + '">' + (hit ? "●" : "") + "</td>";
        }
        html += "</tr>";
      }
      html += "</tbody></table></div>";
    }
    html += "</div>";

    /* 主体表 */
    html += '<div class="card"><h2>主体(' + actors.length + ")</h2>";
    if (!actors.length) {
      html += '<p class="muted">未识别出主体。</p>';
    } else {
      html += '<table class="plain-table"><thead><tr><th>名称</th><th>角色</th><th>证据状态</th></tr></thead><tbody>';
      for (var k = 0; k < actors.length; k++) {
        var ac = actors[k];
        html += "<tr><td>" + escapeHtml(ac.name_as_stated || "—") + "</td><td>" +
          escapeHtml(ac.role || "—") + "</td><td>" + statusTag(ac.evidence_status) + "</td></tr>";
      }
      html += "</tbody></table>";
    }
    html += "</div>";

    /* 程序步骤与期限 */
    html += '<div class="card"><h2>程序步骤与期限</h2>';
    if (!steps.length && !deadlines.length) {
      html += '<p class="muted">未识别出程序步骤或期限。</p>';
    }
    if (steps.length) {
      html += '<ul class="step-list">';
      for (var s = 0; s < steps.length; s++) {
        var stp = steps[s];
        html += "<li>" +
          '<span class="step-date">' + escapeHtml(stp.date_text || "日期待定") + "</span>" +
          '<span class="step-action">' + escapeHtml(stp.action || "") + "</span>" +
          statusTag(stp.evidence_status) +
          "</li>";
      }
      html += "</ul>";
    }
    for (var d = 0; d < deadlines.length; d++) {
      var dl = deadlines[d];
      var dlDs = (dl.date_status === "exact" || dl.date_status === "partial") ? dl.date_status : "unknown";
      html += '<div class="deadline-card ds-box-' + dlDs + '">' +
        '<div class="dl-desc">' + escapeHtml(dl.description || "") + "</div>" +
        '<div class="dl-range">起:' + escapeHtml(dl.start_date || "—") +
        " · 止:" + escapeHtml(dl.end_date || "—") + "</div>" +
        '<div class="dl-status">日期状态:' + escapeHtml(DATE_STATUS_LABEL[dlDs] || dl.date_status || "—") + "</div>" +
        refPills(dl.source_refs) +
        "</div>";
    }
    html += "</div>";

    /* 矛盾与未知 */
    html += '<div class="card"><h2>矛盾与未知(' + uncertainties.length + ")</h2>";
    if (!uncertainties.length) {
      html += '<p class="muted">未发现矛盾或待核实事项。</p>';
    } else {
      html += '<ul class="unc-list">';
      for (var u = 0; u < uncertainties.length; u++) {
        var un = uncertainties[u];
        html += "<li>" +
          '<div class="unc-field">' + escapeHtml(un.field || "") + "</div>" +
          '<div class="unc-reason">' + escapeHtml(un.reason || "") + "</div>" +
          refPills(un.source_refs) +
          "</li>";
      }
      html += "</ul>";
    }
    html += "</div>";

    resultEl.innerHTML = html;

    var exportBtn = resultEl.querySelector("#ev-export");
    if (exportBtn) {
      exportBtn.addEventListener("click", function () {
        downloadBlob((data && data.report_markdown) || "", "证据链梳理报告.md", "text/markdown;charset=utf-8");
      });
    }
  }

  document.getElementById("ev-submit").addEventListener("click", function () {
    var materials = collectMaterials(evEditor);
    if (!materials) return;
    var btn = this;
    var resultEl = document.getElementById("ev-result");
    runTask(btn, resultEl, function () {
      return apiFetch("/api/evidence-chain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ materials: materials })
      }, LONG_TIMEOUT).then(function (data) {
        renderEvidenceChain(data, resultEl);
      });
    });
  });

  /* ============================================================
     ③ 文书起草
     ============================================================ */
  var OVERRIDE_IDS = {
    applicant_name: "ov-applicant",
    review_organ: "ov-organ",
    claims_text: "ov-claims",
    third_party: "ov-third"
  };

  var draftEditor = createMaterialsEditor(document.getElementById("draft-materials"), {
    onLoadSample: function (data) {
      var ov = (data && data.overrides) || {};
      for (var key in OVERRIDE_IDS) {
        if (Object.prototype.hasOwnProperty.call(OVERRIDE_IDS, key) && typeof ov[key] === "string") {
          document.getElementById(OVERRIDE_IDS[key]).value = ov[key];
        }
      }
    }
  });

  function getOverrides() {
    var out = {};
    for (var key in OVERRIDE_IDS) {
      if (Object.prototype.hasOwnProperty.call(OVERRIDE_IDS, key)) {
        out[key] = document.getElementById(OVERRIDE_IDS[key]).value.trim();
      }
    }
    return out;
  }

  function renderDraft(data, resultEl) {
    var notes = (data && data.review_notes) || [];
    var doc = (data && data.document_markdown) || "";

    var html = "";

    /* 审核提示卡(黄色) */
    html += '<div class="card review-card"><h2>审核提示</h2><ul class="plain-list">';
    for (var i = 0; i < notes.length; i++) {
      html += "<li>" + escapeHtml(notes[i]) + "</li>";
    }
    html += '<li class="review-fixed">本文书由 AI 辅助生成,提交前务必人工核对</li>';
    html += "</ul></div>";

    /* 文书预览(渲染为正式文书版式) */
    html += '<div class="card"><h2>文书预览</h2>' +
      '<div class="doc-preview doc-formatted">' + renderDocHtml(doc) + "</div></div>";

    /* 操作行 */
    html += '<div class="card action-row">' +
      '<button type="button" class="btn btn-primary" id="dl-docx">下载 .docx</button>' +
      '<button type="button" class="btn" id="dl-md">下载 .md</button>' +
      '<button type="button" class="btn" id="copy-doc">复制全文</button>' +
      "</div>";

    resultEl.innerHTML = html;

    resultEl.querySelector("#dl-docx").addEventListener("click", function () {
      window.open("/api/draft/download/" + encodeURIComponent((data && data.docx_token) || ""), "_blank");
    });
    resultEl.querySelector("#dl-md").addEventListener("click", function () {
      downloadBlob(doc, "行政复议申请书.md", "text/markdown;charset=utf-8");
    });
    resultEl.querySelector("#copy-doc").addEventListener("click", function () {
      copyText(doc, this);
    });
  }

  document.getElementById("draft-submit").addEventListener("click", function () {
    var materials = collectMaterials(draftEditor);
    if (!materials) return;
    var overrides = getOverrides();
    var btn = this;
    var resultEl = document.getElementById("draft-result");
    runTask(btn, resultEl, function () {
      return apiFetch("/api/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ materials: materials, overrides: overrides })
      }, LONG_TIMEOUT).then(function (data) {
        renderDraft(data, resultEl);
      });
    });
  });

})();
