(function() {
    'use strict';

    /* ========== 轻量 Markdown → HTML（fallback 路径，解析 ** / ` / ## / * / 有序列表 / 无序列表 / 换行） ========== */
    function _mdEscape(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {
            return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] || c;
        });
    }

    function chefSimpleMarkdown(md) {
        if (md == null || md === '') return '';
        let src = _mdEscape(md);

        // ====== 0) 预处理：在单行无换行的报告里，强制在块级语法前插入真实换行（解决截图里"一、…1.蔬菜类：-生菜…-西兰花2.蛋白质"连成一片的问题） ======
        // 0.1 ## / ### 标题前：无论前面是什么字符，都插入 \n\n（保证块级分隔）
        src = src.replace(/(.)(\s*##(?!#))/g, '$1\n\n$2');
        src = src.replace(/(.)(\s*###(?!#))/g, '$1\n\n$2');
        // 0.2 分类号 N. **XXX类**：或 N.XXX类：→ 前面插 \n
        src = src.replace(/(.)(\s*\d+\.\s*\*\*[^*\n]*类[^*\n]*\*\*[:：]?)/g, '$1\n$2');
        src = src.replace(/(.)(\s*\d+\.\s*[^*\n]*类[^*\n]*[:：])/g, '$1\n$2');

        // ----- 0.2b：【食材分类自动编号（前端双保险）】------
        // 把全文按 "## 一、可用食材清单" / "## 二、推荐食谱" 切三段，只在中间段对没有数字序号但写了「Xxx类：/Xxx类:」的行按出现顺序补 1./2./3.
        (function() {
            var h1Re = /(^|\n)(##\s*一、[^\n]*?可用食材清单[^\n]*\n)/;
            var h2Re = /(^|\n)(##\s*二、[^\n]*?推荐食谱[^\n]*\n)/;
            var m1 = src.match(h1Re);
            var m2 = src.match(h2Re);
            var startCat = m1 ? m1.index + m1[0].length : 0;
            var startRec = m2 ? m2.index : src.length;
            if (startCat >= startRec) return; // 没切出食材段，跳过
            var head = src.substring(0, startCat);
            var body = src.substring(startCat, startRec);
            var tail = src.substring(startRec);
            var catCnt = 0;
            // 规则：行首或换行后，无 \d+. 前缀，结尾是「1-20个非-*#`字符 + '类' + 冒号(中/英)」
            body = body.replace(/(^|\n)(\s*)(?!\d+\s*[\.、]\s*)([^\n\-*#`]{1,20}?类)\s*([:：])/gm, function(_, h, sp, name, colon) {
                catCnt += 1;
                return '' + h + sp + catCnt + '. **' + name.replace(/^\s+|\s+$/g, '') + '**' + colon;
            });
            src = head + body + tail;
        })();

        // 0.3 菜序号行：\s*数字. \s*([emoji可选] \s*)**菜名** → 前面插 \n\n（新块开始）
        src = src.replace(/(.)(\s*\d+\.\s+(?:[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F02F}]\s*)?\*\*[^*\n]+?\*\*)/gu, '$1\n\n$2');

        // ----- 0.3b：【推荐食谱菜名自动编号（前端双保险）】------
        // 在「## 二、推荐食谱」之后的段里，对有「**菜名** `营养…难度…`」code胶囊但没有 N. 数字前缀的行，按出现顺序补 1./2./3.
        (function() {
            var h2Re = /(^|\n)(##\s*二、[^\n]*?推荐食谱[^\n]*\n)/;
            var m2 = src.match(h2Re);
            if (!m2) return;
            var startRec = m2.index + m2[0].length;
            var head = src.substring(0, startRec);
            var body = src.substring(startRec);
            var dishCnt = 0;
            var emoSpan = '(?:[\\u{1F300}-\\u{1FAFF}\\u{2600}-\\u{27BF}\\u{1F000}-\\u{1F02F}]\\s*)?';
            // 带营养code胶囊 或 不带code胶囊但 strong 后跟换行/空行（菜名行特征）
            var pat = new RegExp('(^|\\n)(\\s*)(?!\\d+\\s*\\.\\s*)(' + emoSpan + '\\*\\*[^*\\n\\r]+?\\*\\*(?:\\s*`[^`\\n\\r]*营养[^`\\n\\r]*难度[^`\\n\\r]*`)?)', 'gmu');
            body = body.replace(pat, function(_, h, sp, rest) {
                dishCnt += 1;
                return '' + h + sp + dishCnt + '. ' + (rest || '').replace(/^\s+/, '');
            });
            src = head + body;
        })();
        // 0.4 标签 bullet 行：- **X**：/- **X**:（推荐理由/营养价值/制作难度/主要食材/制作步骤/新鲜度点评）→ 前面插 \n
        src = src.replace(/(.)(\s*[-*•]\s*\*\*(推荐理由|营养价值|制作难度|主要食材|制作步骤|新鲜度点评|主食材|副食材|副食材\/调料|调料|蛋白质类|蔬菜类|水果类|主食类)\*\*\s*[:：])/g, '$1\n$2');
        // 0.5 列表 bullet 行（不含上面加粗标签）：\s- 非加粗开头 → 前面插 \n（食材清单的小项拆分）
        src = src.replace(/(.)(\s+[-*•]\s+(?![*•\-\s]))/g, '$1\n$2');
        // 0.6 末尾没有换行就补一个（让收尾列表能被逐行解析器包起来）
        if (!/\n$/.test(src)) src += '\n';

        // 1) Block 级标题 h2 / h3（必须在行首）
        src = src.replace(/^(\s*)##(?!#)[ \t]*([^\n\r]*)/gm, function(_, sp, t) {
            return sp + '<h2>' + (t || '').trim() + '</h2>';
        });
        src = src.replace(/^(\s*)###(?!#)[ \t]*([^\n\r]*)/gm, function(_, sp, t) {
            return sp + '<h3>' + (t || '').trim() + '</h3>';
        });

        // 2) 行内 code：先做，防止 `内部的 `** / * ` 被当成 strong/em
        src = src.replace(/`([^`\n\r]+?)`/g, function(_, code) {
            return '<code>' + code + '</code>';
        });

        // 3) 行内 strong/em
        src = src.replace(/\*\*([^*\n\r]+?)\*\*/g, '<strong>$1</strong>');
        src = src.replace(/__([^_\n\r]+?)__/g, '<strong>$1</strong>');
        src = src.replace(/(^|[^*])\*([^*\n\r]+?)\*(?!\*)/g, '$1<em>$2</em>');
        src = src.replace(/(^|[^_])_([^_\n\r]+?)_(?!_)/g, '$1<em>$2</em>');

        // 4) Blockquote
        src = src.replace(/^\s*>[ \t]*([^\n\r]*)/gm, function(_, line) {
            return '<blockquote>' + line + '</blockquote>';
        });

        // 5) Lists：逐行遍历，把相邻数字序号行 / bullet 行分别包进 <ol><li> / <ul><li>
        const inputLines = src.split(/\r?\n/);
        const out = [];
        let i = 0;
        while (i < inputLines.length) {
            const line = inputLines[i];

            const olM = line.match(/^(\s*)(\d+)\.[ \t]+(.+)$/);
            if (olM) {
                const indent = olM[1];
                const items = [];
                while (i < inputLines.length) {
                    const m = inputLines[i].match(/^(\s*)(\d+)\.[ \t]+(.+)$/);
                    if (m && m[1] === indent) {
                        items.push(m[3]);
                        i++;
                        continue;
                    }
                    break;
                }
                out.push('<ol start="' + (parseInt(olM[2], 10) || 1) + '">' + items.map(it => '<li>' + it + '</li>').join('') + '</ol>');
                continue;
            }

            const ulM = line.match(/^(\s*)([-*•])[ \t]+(.+)$/);
            if (ulM) {
                const indent = ulM[1];
                const items = [];
                while (i < inputLines.length) {
                    const m = inputLines[i].match(/^(\s*)([-*•])[ \t]+(.+)$/);
                    if (m && m[1] === indent) {
                        items.push(m[3]);
                        i++;
                        continue;
                    }
                    break;
                }
                out.push('<ul>' + items.map(it => '<li>' + it + '</li>').join('') + '</ul>');
                continue;
            }

            if (line.trim() === '') {
                out.push('');
                i++;
                continue;
            }

            // 普通行：块级标签（<h2>/<h3>/<ol>/<ul>/<blockquote>）不加 <br>；其它末尾加 <br>
            if (/^\s*<(h2|h3|ol|ul|blockquote)\b/i.test(line) || /^\s*<\/(ol|ul|blockquote)>/i.test(line)) {
                out.push(line);
            } else {
                out.push(line + '<br>');
            }
            i++;
        }
        return out.join('\n');
    }

    /* ========== 卡片徽章后处理（菜图徽章：JS 按菜名自动生成 + emoji 徽章抽取排序） ========== */
    // 菜名 → emoji（与后端 Python 保持一致）
    var _CHEF_DISH_EMOJI_RULES = [
        [["沙拉","生菜","油醋汁","凉拌","冷盘","冷菜"], "🥗"],
        [["三文鱼","刺身"], "🐟"],
        [["鱼","鲈鱼","鲫鱼","鲤鱼","带鱼","鳕鱼","蒸鱼","水煮鱼","酸菜鱼","红烧鱼","烤鱼"], "🐟"],
        [["虾","虾仁","大虾","基围虾","白灼虾","油焖虾"], "🦐"],
        [["鸡胸","鸡腿","鸡翅","鸡","鸡丁","辣子鸡","黄焖鸡","炸鸡","烤鸡"], "🍗"],
        [["牛","牛排","牛腩","牛肉","黑椒牛","肥牛"], "🥩"],
        [["猪","猪肉","里脊","排骨","五花","腊肉","培根"], "🥓"],
        [["烤","烤盘","焗","烤箱","炙","锡纸","烧"], "🥘"],
        [["炒","爆","熘","回锅","快炒","小炒"], "🔥"],
        [["汤","羹","煲","炖","煮"], "🍲"],
        [["意面"], "🍜"],
        [["面","面条","拉面","拌面","炒面","挂面"], "🍜"],
        [["炒饭","烩饭","焗饭"], "🍛"],
        [["饭","米饭","泡饭","粥","焖饭"], "🍚"],
        [["蛋","鸡蛋","炒蛋","煎蛋","蛋羹","蛋饼","蒸蛋"], "🥚"],
        [["西兰花","素菜","时蔬","蔬菜","青菜","芥兰","芦笋","菠菜"], "🥦"],
        [["海鲜","蟹","扇贝","生蚝","龙虾","鱿鱼","花甲"], "🦞"],
        [["盖饭","盖浇饭","便当","饭盒"], "🍱"],
        [["饺子","锅贴","馄饨","包子","小笼"], "🥟"],
        [["火锅","麻辣烫","串串","冒菜"], "🍲"],
        [["披萨","比萨","pizza"], "🍕"],
        [["寿司","饭团","紫菜包饭"], "🍣"]
    ];
    // 菜名 → LoremFlickr 英文 tags（与后端 Python 保持一致）
    var _CHEF_DISH_TAG_RULES = [
        [["沙拉","生菜","油醋汁","凉拌","冷盘","冷菜"], ["salad","green-salad"]],
        [["三文鱼","刺身"], ["salmon","sashimi"]],
        [["鱼","鲈鱼","鲫鱼","鲤鱼","带鱼","鳕鱼","蒸鱼","水煮鱼","酸菜鱼","红烧鱼","烤鱼"], ["fish","fish-dish","seafood"]],
        [["虾","虾仁","大虾","基围虾","白灼虾","油焖虾"], ["shrimp","prawn","seafood"]],
        [["鸡胸","鸡腿","鸡翅","鸡","鸡丁","辣子鸡","黄焖鸡","炸鸡","烤鸡"], ["chicken","chicken-breast"]],
        [["牛","牛排","牛腩","牛肉","黑椒牛","肥牛"], ["beef","steak"]],
        [["猪","猪肉","里脊","排骨","五花","腊肉","培根"], ["pork","bacon"]],
        [["烤","烤盘","焗","烤箱","炙","锡纸","烧"], ["roasted","grilled","oven"]],
        [["炒","爆","熘","回锅","快炒","小炒"], ["stir-fry","wok"]],
        [["汤","羹","煲","炖","煮"], ["soup","stew"]],
        [["意面"], ["pasta","spaghetti"]],
        [["面","面条","拉面","拌面","炒面","挂面"], ["noodles","ramen"]],
        [["炒饭","烩饭","焗饭"], ["fried-rice","rice"]],
        [["饭","米饭","泡饭","粥","焖饭"], ["rice","congee"]],
        [["蛋","鸡蛋","炒蛋","煎蛋","蛋羹","蛋饼","蒸蛋"], ["egg","omelette"]],
        [["西兰花","素菜","时蔬","蔬菜","青菜","芥兰","芦笋","菠菜"], ["vegetable","broccoli"]],
        [["海鲜","蟹","扇贝","生蚝","龙虾","鱿鱼","花甲"], ["seafood","lobster"]],
        [["盖饭","盖浇饭","便当","饭盒"], ["rice-bowl","bento"]],
        [["饺子","锅贴","馄饨","包子","小笼"], ["dumplings","jiaozi"]],
        [["火锅","麻辣烫","串串","冒菜"], ["hotpot","soup"]],
        [["披萨","比萨","pizza"], ["pizza"]],
        [["寿司","饭团","紫菜包饭"], ["sushi"]],
        [["蘑菇"], ["mushroom"]],
        [["彩椒","甜椒","青椒"], ["bell-pepper"]],
        [["番茄","西红柿"], ["tomato"]],
        [["柠檬"], ["lemon"]]
    ];
    function _chefMatchEmoji(name) {
        if (!name) return '🍽';
        var n = String(name).toLowerCase();
        for (var i = 0; i < _CHEF_DISH_EMOJI_RULES.length; i++) {
            var kws = _CHEF_DISH_EMOJI_RULES[i][0];
            for (var j = 0; j < kws.length; j++) {
                if (n.indexOf(kws[j].toLowerCase()) >= 0) return _CHEF_DISH_EMOJI_RULES[i][1];
            }
        }
        return '🍽';
    }
    function _chefMatchTags(name) {
        if (!name) return ['food','dish'];
        var tags = [], seen = {};
        var push = function(t) { if (!seen[t]) { seen[t]=1; tags.push(t); } };
        for (var i = 0; i < _CHEF_DISH_TAG_RULES.length; i++) {
            var kws = _CHEF_DISH_TAG_RULES[i][0];
            var tg = _CHEF_DISH_TAG_RULES[i][1];
            var hit = false;
            for (var j = 0; j < kws.length; j++) {
                if (name.indexOf(kws[j]) >= 0 || name.toLowerCase().indexOf(kws[j].toLowerCase()) >= 0) { hit = true; break; }
            }
            if (hit) {
                for (var k = 0; k < tg.length; k++) push(tg[k]);
                if (tags.length >= 3) break;
            }
        }
        push('food'); push('dish'); push('cooking');
        return tags.slice(0, 3);
    }
    function _chefMd5(s) {
        // 轻量稳定 hash：djb2（只需要 8 位 hex，保证"同一菜名→同一 lock 字符串→同一 LoremFlickr 图"即可）
        // 不依赖真实 md5 实现，避免 undefined 变量抛错
        var h1 = 5381;
        var src = String(s == null ? '' : s);
        for (var i2 = 0; i2 < src.length; i2++) {
            h1 = ((h1 << 5) + h1) ^ src.charCodeAt(i2);
        }
        // djb2 是 32 位有符号，再拼一个简易的另一半 hash（旋转 13 位异或），让 8 位 hex 分布更散
        var h2 = 0x811c9dc5;
        for (var i3 = 0; i3 < src.length; i3++) {
            h2 ^= src.charCodeAt(i3);
            h2 = Math.imul(h2, 0x01000193) >>> 0;
        }
        var hex1 = (h1 >>> 0).toString(16);
        var hex2 = (h2 >>> 0).toString(16);
        while (hex1.length < 8) hex1 = '0' + hex1;
        while (hex2.length < 8) hex2 = '0' + hex2;
        // 取前 4 位 + 后 4 位，凑 8 位
        return (hex1.slice(0, 4) + hex2.slice(4, 8)).slice(0, 8);
    }
    function _chefLockSeed(s) { return _chefMd5(s); }

    // 主入口：对助手消息内容容器做"emoji 徽章 + 文本下方大图"后处理（流式/REPLACE/fallback 都调这个）
    function __chefApplyCardBadges(contentEl) {
        if (!contentEl) return;
        var allOls = contentEl.querySelectorAll('ol');
        if (!allOls || allOls.length === 0) return;

        // ====== 仅针对"推荐食谱分区"（第二个 <ol>；或单 ol 启发式判断）======
        var dishOl = null;
        if (allOls.length >= 2) {
            dishOl = allOls[1];
        } else {
            var onlyOl = allOls[0];
            var lisTest = onlyOl.querySelectorAll('li');
            var dishScore = 0;
            for (var ti = 0; ti < lisTest.length && ti < 3; ti++) {
                var ht = (lisTest[ti].innerHTML || '');
                if (ht.indexOf('</strong>') !== -1 && /营养[^`\/]*难度|<code>/.test(ht)) dishScore++;
            }
            if (dishScore > 0) dishOl = onlyOl;
        }
        if (!dishOl) return;

        var lis = dishOl.children;
        for (var li = 0; li < lis.length; li++) {
            var node = lis[li];
            if (!node) continue;

            // ---- 0) 清理可能残留的小徽章（如果之前的版本创建了，新版全部清掉）
            var oldBadges = node.querySelectorAll(':scope > .dish-image-badge');
            for (var ob = 0; ob < oldBadges.length; ob++) {
                if (oldBadges[ob].parentNode) oldBadges[ob].parentNode.removeChild(oldBadges[ob]);
            }
            // 清理可能残留的 emoji 徽章移到不显眼位置（保留功能但视觉弱化）
            var oldEmojis = node.querySelectorAll(':scope > .dish-emoji-badge');
            for (var oe = 0; oe < oldEmojis.length; oe++) {
                // 把 emoji 徽章移到菜卡底部（不再在序号旁抢视觉）
                var oeEl = oldEmojis[oe];
                if (oeEl.parentNode && oeEl.parentNode !== node) {
                    oeEl.parentNode.removeChild(oeEl);
                    node.appendChild(oeEl);
                } else if (oeEl.parentNode === node) {
                    // 已经是 li 直接子节点，移到末尾
                    if (node.lastChild !== oeEl) node.appendChild(oeEl);
                }
            }

            // ---- 1) emoji 徽章：优先从行首文本抽；否则按菜名 strong 自动补（移到菜卡底部）
            if (node.getAttribute('data-dish-emoji-processed') !== '1') {
                var firstEmoji = null, emojiTextNode = null;
                var walker = node.childNodes;
                for (var wi = 0; wi < walker.length; wi++) {
                    var ch = walker[wi];
                    if (ch.nodeType === 3) {
                        var mEmo = ch.nodeValue.match(/^(\s*)([\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F02F}])(\s*)/u);
                        if (mEmo) { firstEmoji = mEmo[2]; emojiTextNode = ch; break; }
                    } else if (ch.nodeType === 1) {
                        var tg = (ch.tagName || '').toUpperCase();
                        if (tg === 'STRONG') break;
                        if (tg === 'SPAN' && /dish-(image|emoji)-badge/.test(ch.className || '')) continue;
                    }
                }
                if (!firstEmoji) {
                    var strongs2 = node.querySelectorAll(':scope > strong, :scope > p > strong:first-child');
                    if (strongs2 && strongs2.length > 0) firstEmoji = _chefMatchEmoji(strongs2[0].textContent || '');
                }
                if (firstEmoji && emojiTextNode) {
                    var prefix = emojiTextNode.nodeValue;
                    prefix = prefix.replace(/^(\s*)[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F02F}](\s*)/u, '$1$3');
                    emojiTextNode.nodeValue = prefix;
                }
                if (firstEmoji) {
                    var badge = document.createElement('span');
                    badge.className = 'dish-emoji-badge dish-emoji-badge-bottom';
                    badge.textContent = firstEmoji;
                    // 插入到 li 底部（文本之后）
                    node.appendChild(badge);
                }
                node.setAttribute('data-dish-emoji-processed', '1');
            }

            // ---- 2) 【核心】文本下方大图：在"推荐理由/营养价值"等文本之后、"制作步骤"之前，插入一张全宽配图
            if (node.getAttribute('data-dish-hero-image-processed') !== '1') {
                var strongsHero = node.querySelectorAll(':scope > strong, :scope > p > strong:first-child');
                var heroDishName = '';
                if (strongsHero && strongsHero.length > 0) heroDishName = (strongsHero[0].textContent || '').trim();
                if (heroDishName) {
                    var heroTags = _chefMatchTags(heroDishName);
                    var heroLock = _chefLockSeed(heroDishName);
                    // 大图：640×400，更宽更高，文本下方展示
                    var heroUrl = 'https://loremflickr.com/640/400/' + heroTags.join(',') + '?lock=' + encodeURIComponent(heroLock);
                    var heroImg = document.createElement('img');
                    heroImg.src = heroUrl;
                    heroImg.alt = heroDishName;
                    heroImg.className = 'dish-hero-image';
                    heroImg.setAttribute('referrerpolicy', 'no-referrer');
                    heroImg.setAttribute('loading', 'lazy');
                    heroImg.setAttribute('decoding', 'async');
                    heroImg.setAttribute('crossorigin', 'anonymous');
                    // 图片失败：渐变底 + 菜名大字占位
                    heroImg.onerror = function() {
                        try {
                            var fb = this.parentNode;
                            if (!fb || !fb.classList) return;
                            fb.classList.add('dish-hero-failed');
                            this.style.display = 'none';
                            var altText = this.getAttribute('alt') || '';
                            try {
                                var txtEl = document.createElement('span');
                                txtEl.className = 'dish-hero-fallback-text';
                                txtEl.textContent = altText;
                                if (fb.appendChild) fb.appendChild(txtEl);
                            } catch(et) {}
                        } catch(e) {}
                    };
                    var heroWrap = document.createElement('div');
                    heroWrap.className = 'dish-hero-image-wrap';
                    heroWrap.appendChild(heroImg);

                    // 插入位置：找「制作步骤」标签之前（文本下方、步骤上方）——这是最符合"文字下方展示图片"要求的位置
                    var targetBefore = null;
                    var subItems = node.children;
                    for (var ci = 0; ci < subItems.length; ci++) {
                        var cEl = subItems[ci];
                        if (cEl.nodeType !== 1) continue;
                        var htext = (cEl.textContent || '').slice(0, 30);
                        if (htext.indexOf('制作步骤') !== -1 || htext.indexOf('做法') !== -1) {
                            targetBefore = cEl; break;
                        }
                    }
                    if (!targetBefore) {
                        // 找不到制作步骤：找"主要食材"之后
                        for (var cj = 0; cj < subItems.length; cj++) {
                            var cjEl = subItems[cj];
                            if (cjEl.nodeType !== 1) continue;
                            var cjText = (cjEl.textContent || '').slice(0, 30);
                            if (cjText.indexOf('主要食材') !== -1) {
                                targetBefore = subItems[cj + 1] || null;
                                break;
                            }
                        }
                    }
                    if (targetBefore) node.insertBefore(heroWrap, targetBefore);
                    else node.insertBefore(heroWrap, node.lastChild);
                }
                node.setAttribute('data-dish-hero-image-processed', '1');
            }
        }
    }
    // 暴露给 fallback appendMessage 调用
    window.__chefApplyCardBadges = __chefApplyCardBadges;

    var DEFAULT_THEME = 'sage';
    var VALID_THEMES = ['sage', 'misty-blue', 'dusty-rose', 'mauve', 'warm-gray', 'terracotta'];

    function applySavedTheme() {
        var savedTheme = localStorage.getItem('theme') || DEFAULT_THEME;
        if (VALID_THEMES.indexOf(savedTheme) === -1) {
            savedTheme = DEFAULT_THEME;
            localStorage.setItem('theme', DEFAULT_THEME);
        }
        var savedMode = localStorage.getItem('mode') || 'light';
        if (savedTheme !== DEFAULT_THEME) {
            document.documentElement.setAttribute('data-theme', savedTheme);
        } else {
            document.documentElement.removeAttribute('data-theme');
        }
        if (savedMode === 'dark') {
            document.documentElement.setAttribute('data-mode', 'dark');
        }
        updateThemeDots();
        updateDarkToggle();
    }

    function setTheme(theme) {
        if (theme === DEFAULT_THEME) {
            document.documentElement.removeAttribute('data-theme');
        } else {
            document.documentElement.setAttribute('data-theme', theme);
        }
        localStorage.setItem('theme', theme);
        updateThemeDots();
    }

    function toggleDarkMode() {
        var html = document.documentElement;
        var isDark = html.getAttribute('data-mode') === 'dark';
        if (isDark) {
            html.removeAttribute('data-mode');
            localStorage.setItem('mode', 'light');
        } else {
            html.setAttribute('data-mode', 'dark');
            localStorage.setItem('mode', 'dark');
        }
        updateDarkToggle();
    }

    function updateThemeDots() {
        var currentTheme = document.documentElement.getAttribute('data-theme') || DEFAULT_THEME;
        var dots = document.querySelectorAll('.chef-theme-dot');
        for (var i = 0; i < dots.length; i++) {
            if (dots[i].getAttribute('data-theme') === currentTheme) {
                dots[i].classList.add('active');
            } else {
                dots[i].classList.remove('active');
            }
        }
    }

    function updateDarkToggle() {
        var isDark = document.documentElement.getAttribute('data-mode') === 'dark';
        var toggle = document.getElementById('chefDarkToggle');
        if (toggle) {
            if (isDark) {
                toggle.classList.add('active');
            } else {
                toggle.classList.remove('active');
            }
        }
    }

    /* ========== 会话管理 ========== */
    var CHEF_USER_ID = localStorage.getItem('mailfriend_current_user') || 'chef_default';
    var CHEF_BIZ_TYPE = 'chef';

    function escapeHtml(str) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    function formatRelativeTime(isoStr) {
        if (!isoStr) return '';
        try {
            var d = new Date(isoStr);
            if (isNaN(d.getTime())) {
                // 日期无效，尝试其他格式
                // 如果包含 ISO 格式的子串
                var match = String(isoStr).match(/(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})/);
                if (match) {
                    d = new Date(match[1]);
                }
                if (isNaN(d.getTime())) {
                    return ''; // 返回空字符串
                }
            }
            var now = new Date();
            var diff = (now - d) / 1000;
            if (diff < 0) diff = Math.abs(diff); // 防止时区问题
            if (diff < 60) return '刚刚';
            if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
            if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
            if (diff < 604800) return Math.floor(diff / 86400) + ' 天前';
            return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
        } catch (e) {
            return '';
        }
    }

    function getCurrentThreadId() {
        return localStorage.getItem('thread_id') || '';
    }

    function setCurrentThreadId(threadId) {
        localStorage.setItem('thread_id', threadId);
        localStorage.setItem('chef_current_thread_id', threadId);
    }

    function clearCurrentThreadId() {
        localStorage.removeItem('thread_id');
        localStorage.removeItem('chef_current_thread_id');
    }

    /* ========== 批量管理 ========== */
    var chefBatchMode = false;
    var chefSelectedThreads = {};

    function chefEnterBatchMode() {
        chefBatchMode = true;
        chefSelectedThreads = {};
        var list = document.getElementById('chefSessionList');
        if (list) list.classList.add('batch-mode');
        var bar = document.getElementById('chefBatchActionBar');
        if (bar) bar.classList.add('show');
        var editBtn = document.getElementById('chefBatchEditBtn');
        if (editBtn) editBtn.style.display = 'none';
        chefUpdateBatchUI();
    }

    function chefExitBatchMode() {
        chefBatchMode = false;
        chefSelectedThreads = {};
        var list = document.getElementById('chefSessionList');
        if (list) list.classList.remove('batch-mode');
        var bar = document.getElementById('chefBatchActionBar');
        if (bar) bar.classList.remove('show');
        var editBtn = document.getElementById('chefBatchEditBtn');
        if (editBtn) editBtn.style.display = '';
        var items = document.querySelectorAll('.chef-session-item');
        items.forEach(function(item) {
            item.classList.remove('selected');
            var cb = item.querySelector('.chef-session-checkbox');
            if (cb) cb.checked = false;
        });
        var sa = document.getElementById('chefBatchSelectAll');
        if (sa) sa.checked = false;
    }

    function chefToggleSelectItem(item, threadId) {
        if (chefSelectedThreads[threadId]) {
            delete chefSelectedThreads[threadId];
            item.classList.remove('selected');
            var cb = item.querySelector('.chef-session-checkbox');
            if (cb) cb.checked = false;
        } else {
            chefSelectedThreads[threadId] = true;
            item.classList.add('selected');
            var cb2 = item.querySelector('.chef-session-checkbox');
            if (cb2) cb2.checked = true;
        }
        chefUpdateBatchUI();
    }

    function chefUpdateBatchUI() {
        var count = Object.keys(chefSelectedThreads).length;
        var countEl = document.getElementById('chefBatchCount');
        if (countEl) countEl.textContent = '已选 ' + count + ' 项';
        var delBtn = document.getElementById('chefBatchDeleteBtn');
        if (delBtn) delBtn.disabled = count === 0;
        var items = document.querySelectorAll('.chef-session-item');
        var allChecked = items.length > 0 && count === items.length;
        var sa = document.getElementById('chefBatchSelectAll');
        if (sa) sa.checked = allChecked;
        items.forEach(function(item) {
            var tid = item.getAttribute('data-thread-id');
            var cb = item.querySelector('.chef-session-checkbox');
            if (chefSelectedThreads[tid]) {
                item.classList.add('selected');
                if (cb) cb.checked = true;
            } else {
                item.classList.remove('selected');
                if (cb) cb.checked = false;
            }
        });
    }

    function chefSelectAllBatch(checked) {
        var items = document.querySelectorAll('.chef-session-item');
        items.forEach(function(item) {
            var tid = item.getAttribute('data-thread-id');
            var cb = item.querySelector('.chef-session-checkbox');
            if (checked) {
                chefSelectedThreads[tid] = true;
                item.classList.add('selected');
                if (cb) cb.checked = true;
            } else {
                delete chefSelectedThreads[tid];
                item.classList.remove('selected');
                if (cb) cb.checked = false;
            }
        });
        chefUpdateBatchUI();
    }

    function chefDeleteSelectedBatch() {
        var tids = Object.keys(chefSelectedThreads);
        if (tids.length === 0) return;
        if (!confirm('确定要删除选中的 ' + tids.length + ' 个会话吗？此操作不可撤销。')) return;
        var delBtn = document.getElementById('chefBatchDeleteBtn');
        if (delBtn) { delBtn.disabled = true; delBtn.textContent = '删除中...'; }
        var promises = tids.map(function(tid) {
            return fetch('/api/v1/sessions/' + tid, { method: 'DELETE' })
                .then(function(r) { if (!r.ok) throw new Error('删除失败'); return r.json(); })
                .catch(function(e) { console.error('删除会话失败 ' + tid + ':', e); });
        });
        Promise.all(promises).then(function() {
            var currentTid = getCurrentThreadId();
            if (chefSelectedThreads[currentTid]) {
                clearCurrentThreadId();
                var chatArea = getChatArea();
                if (chatArea) chatArea.innerHTML = '';
                chefExitBatchMode();
                loadSessions();
                createNewSession();
            } else {
                chefExitBatchMode();
                loadSessions();
            }
            if (delBtn) {
                delBtn.disabled = false;
                delBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>删除所选';
            }
        });
    }

    function loadSessions() {
        fetch('/api/v1/sessions?user_id=' + encodeURIComponent(CHEF_USER_ID) + '&biz_type=' + CHEF_BIZ_TYPE)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var list = document.getElementById('chefSessionList');
                if (!list) return;
                list.innerHTML = '';
                var sessions = Array.isArray(data) ? data : (data.sessions || []);
                if (sessions.length === 0) {
                    list.innerHTML = '<div class="chef-session-empty">暂无会话<br>点击上方按钮新建</div>';
                    return;
                }
                var currentThreadId = getCurrentThreadId();
                sessions.forEach(function(s) {
                    var item = document.createElement('div');
                    item.className = 'chef-session-item';
                    item.setAttribute('data-thread-id', s.thread_id);
                    if (s.thread_id === currentThreadId) {
                        item.classList.add('active');
                    }
                    var title = s.name || '新会话';
                    var time = formatRelativeTime(s.updated_at || s.created_at);
                    item.innerHTML =
                        '<input type="checkbox" class="chef-session-checkbox" data-thread-id="' + s.thread_id + '">' +
                        '<div class="chef-session-info">' +
                        '<div class="chef-session-title">' + escapeHtml(title) + '</div>' +
                        '<div class="chef-session-meta">' + time + '</div>' +
                        '</div>' +
                        '<button class="chef-session-delete" title="删除会话">' +
                        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>' +
                        '</button>';
                    item.querySelector('.chef-session-info').addEventListener('click', function() {
                        if (chefBatchMode) {
                            chefToggleSelectItem(item, s.thread_id);
                            return;
                        }
                        switchSession(s.thread_id);
                    });
                    item.querySelector('.chef-session-checkbox').addEventListener('click', function(e) {
                        e.stopPropagation();
                        chefToggleSelectItem(item, s.thread_id);
                    });
                    item.querySelector('.chef-session-delete').addEventListener('click', function(e) {
                        e.stopPropagation();
                        deleteSession(s.thread_id);
                    });
                    list.appendChild(item);
                });
                if (chefBatchMode) chefUpdateBatchUI();
            })
            .catch(function() {
                var list = document.getElementById('chefSessionList');
                if (list) {
                    list.innerHTML = '<div class="chef-session-empty">加载会话失败</div>';
                }
            });
    }

    function getChatArea() {
        // 获取聊天区域（查找消息容器）
        return document.querySelector('.flex-1.overflow-y-auto') || 
               document.querySelector('[class*="chat"].flex-1') ||
               document.querySelector('.chef-chat-content');
    }

    function deleteSession(threadId) {
        if (!confirm('确定要删除这个会话吗？')) return;
        fetch('/api/v1/sessions/' + threadId, { method: 'DELETE' })
            .then(function(r) {
                if (!r.ok) throw new Error('删除失败');
                return r.json();
            })
            .then(function() {
                var currentThreadId = getCurrentThreadId();
                if (currentThreadId === threadId) {
                    clearCurrentThreadId();
                    // 清空聊天区域
                    var chatArea = getChatArea();
                    if (chatArea) chatArea.innerHTML = '';
                    // 重新加载会话列表
                    loadSessions();
                    // 自动创建新会话
                    createNewSession();
                } else {
                    loadSessions();
                }
            })
            .catch(function(e) {
                console.error('删除会话失败:', e);
                alert('删除会话失败：' + e.message);
            });
    }

    function switchSession(threadId) {
        if (getCurrentThreadId() === threadId) return; // 已选中
        setCurrentThreadId(threadId);
        // 标记当前会话
        var items = document.querySelectorAll('.chef-session-item');
        items.forEach(function(item) {
            if (item.getAttribute('data-thread-id') === threadId) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });
        // 加载历史消息
        loadSessionMessages(threadId);
    }

    function loadSessionMessages(threadId) {
        var chatArea = getChatArea();
        if (!chatArea) {
            console.error('找不到聊天区域');
            return;
        }
        
        chatArea.innerHTML = '<div class="chef-session-empty">加载中...</div>';
        
        fetch('/api/v1/sessions/' + threadId + '/messages?biz_type=chef')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                chatArea.innerHTML = '';
                var messages = data.messages || [];
                if (messages.length === 0) {
                    chatArea.innerHTML = '<div class="chef-session-empty">该会话暂无消息，请开始对话</div>';
                    return;
                }
                // 渲染历史消息
                messages.forEach(function(msg) {
                    var role = (msg.role === 'human' || msg.role === 'user') ? 'user' : 'assistant';
                    var content = msg.content || '';
                    if (content && typeof content === 'string') {
                        // 创建消息元素
                        appendMessageToArea(chatArea, role, content);
                    }
                });
                chatArea.scrollTop = chatArea.scrollHeight;
            })
            .catch(function(e) {
                console.error('加载消息失败:', e);
                chatArea.innerHTML = '<div class="chef-session-empty">加载消息失败，请刷新页面重试</div>';
            });
    }

    function appendMessageToArea(area, role, text, image) {
        var msg = document.createElement('div');
        msg.className = role === 'user' ? 'chef-msg chef-msg-user' : 'chef-msg chef-msg-assistant';

        var avatar = role === 'user'
            ? '<div class="chef-msg-avatar chef-msg-avatar-user"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg></div>'
            : '<div class="chef-msg-avatar"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21a1 1 0 0 0 1-1v-5.35c0-.457.316-.844.727-1.041a4 4 0 0 0-2.134-7.589 5 5 0 0 0-9.186 0 4 4 0 0 0-2.134 7.588c.411.198.727.585.727 1.041V20a1 1 0 0 0 1 1Z"/><path d="M6 17h12"/></svg></div>';

        var content = '<div class="chef-msg-content">';
        if (image) {
            content += '<img src="' + image + '" style="max-width:200px;max-height:200px;border-radius:8px;margin-bottom:8px;display:block;">';
        }
        if (text) {
            if (role === 'assistant') {
                content += chefSimpleMarkdown(text);
            } else {
                content += escapeHtml(text).replace(/\n/g, '<br>');
            }
        }
        content += '</div>';

        msg.innerHTML = avatar + content;
        // 应用卡片徽章
        if (role === 'assistant') {
            var _contentEl = msg.querySelector('.chef-msg-content');
            if (_contentEl && typeof __chefApplyCardBadges === 'function') {
                __chefApplyCardBadges(_contentEl);
            }
        }
        area.appendChild(msg);
    }

    function createNewSession() {
        fetch('/api/v1/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: CHEF_USER_ID,
                biz_type: CHEF_BIZ_TYPE,
                name: 'AI 私厨会话 ' + new Date().toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
            })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.thread_id) {
                setCurrentThreadId(data.thread_id);
                // 切换到新会话并清空聊天区域
                var chatArea = getChatArea();
                if (chatArea) {
                    chatArea.innerHTML = '<div class="chef-session-empty">新会话已创建，请开始对话</div>';
                }
                // 重新加载会话列表
                loadSessions();
            }
        })
        .catch(function(e) {
            console.error('创建会话失败:', e);
            alert('创建会话失败：' + e.message);
        });
    }

    /* ========== 与原始应用联动 ========== */

    function reloadPage() {
        // 刷新页面让原始 Next.js 应用重新加载 thread_id 和消息
        // 使用 setTimeout 确保 localStorage 写入完成
        setTimeout(function() {
            window.location.reload();
        }, 100);
    }

    // 监听来自原始应用的消息（如果原始应用通过 BroadcastChannel 或其他方式通信）
    window.addEventListener('storage', function(e) {
        if (e.key === 'thread_id' && e.newValue) {
            // 原始应用可能设置了新的 thread_id
            var items = document.querySelectorAll('.chef-session-item');
            for (var i = 0; i < items.length; i++) {
                if (items[i].getAttribute('data-thread-id') === e.newValue) {
                    items[i].classList.add('active');
                } else {
                    items[i].classList.remove('active');
                }
            }
        }
    });

    function toggleSettings() {
        var panel = document.getElementById('chefSettingsPopover');
        if (panel) {
            panel.classList.toggle('show');
        }
    }

    function goHome() {
        window.location.href = '/';
    }

    /* ========== 构建常驻侧边栏 ========== */
    function buildSidebar() {
        var sidebar = document.createElement('aside');
        sidebar.id = 'chefSessionSidebar';
        sidebar.className = 'chef-session-sidebar';
        sidebar.innerHTML =
            '<div class="chef-session-header">' +
            '  <div class="chef-session-brand">' +
            '    <div class="chef-session-brand-icon">' +
            '      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21a1 1 0 0 0 1-1v-5.35c0-.457.316-.844.727-1.041a4 4 0 0 0-2.134-7.589 5 5 0 0 0-9.186 0 4 4 0 0 0-2.134 7.588c.411.198.727.585.727 1.041V20a1 1 0 0 0 1 1Z"/><path d="M6 17h12"/></svg>' +
            '    </div>' +
            '    <span class="chef-session-brand-text">AI 私厨</span>' +
            '  </div>' +
            '  <button class="chef-new-session" id="chefNewSession">' +
            '    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>' +
            '    新建会话' +
            '  </button>' +
            '</div>' +
            '<div class="chef-batch-toolbar">' +
            '  <span class="chef-batch-toolbar-title">会话记录</span>' +
            '  <button class="chef-batch-edit-btn" id="chefBatchEditBtn" title="批量管理">' +
            '    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>' +
            '    批量管理' +
            '  </button>' +
            '</div>' +
            '<div class="chef-session-list" id="chefSessionList"></div>' +
            '<div class="chef-batch-action-bar" id="chefBatchActionBar">' +
            '  <label class="chef-batch-select-all">' +
            '    <input type="checkbox" id="chefBatchSelectAll">' +
            '    <span>全选</span>' +
            '  </label>' +
            '  <span class="chef-batch-count" id="chefBatchCount">已选 0 项</span>' +
            '  <div class="chef-batch-action-btns">' +
            '    <button class="chef-batch-action-btn chef-batch-delete-btn" id="chefBatchDeleteBtn">' +
            '      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>' +
            '      删除所选' +
            '    </button>' +
            '    <button class="chef-batch-action-btn chef-batch-cancel-btn" id="chefBatchCancelBtn">取消</button>' +
            '  </div>' +
            '</div>' +
            '<div class="chef-session-footer">' +
            '  <button class="chef-session-footer-btn" id="chefSettingsBtn">' +
            '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>' +
            '    设置' +
            '  </button>' +
            '  <button class="chef-session-footer-btn" id="chefHomeBtn">' +
            '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>' +
            '    首页' +
            '  </button>' +
            '</div>';
        document.body.appendChild(sidebar);

        var popover = document.createElement('div');
        popover.id = 'chefSettingsPopover';
        popover.className = 'chef-settings-popover';
        popover.innerHTML =
            '<h4>主题颜色</h4>' +
            '<div class="chef-theme-grid">' +
            '  <button class="chef-theme-dot" data-theme="sage" title="鼠尾草绿"></button>' +
            '  <button class="chef-theme-dot" data-theme="misty-blue" title="雾霾蓝"></button>' +
            '  <button class="chef-theme-dot" data-theme="dusty-rose" title="灰玫瑰"></button>' +
            '  <button class="chef-theme-dot" data-theme="mauve" title="藕荷紫"></button>' +
            '  <button class="chef-theme-dot" data-theme="warm-gray" title="暖灰"></button>' +
            '  <button class="chef-theme-dot" data-theme="terracotta" title="陶土"></button>' +
            '</div>' +
            '<div class="chef-setting-row">' +
            '  <span class="chef-setting-row-label">夜间模式</span>' +
            '  <button class="chef-dark-toggle" id="chefDarkToggle" title="切换夜间模式">' +
            '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>' +
            '  </button>' +
            '</div>';
        document.body.appendChild(popover);

        document.getElementById('chefNewSession').addEventListener('click', createNewSession);
        document.getElementById('chefSettingsBtn').addEventListener('click', toggleSettings);
        document.getElementById('chefHomeBtn').addEventListener('click', goHome);
        document.getElementById('chefDarkToggle').addEventListener('click', toggleDarkMode);

        // 批量管理
        document.getElementById('chefBatchEditBtn').addEventListener('click', chefEnterBatchMode);
        document.getElementById('chefBatchCancelBtn').addEventListener('click', chefExitBatchMode);
        document.getElementById('chefBatchSelectAll').addEventListener('change', function() {
            chefSelectAllBatch(this.checked);
        });
        document.getElementById('chefBatchDeleteBtn').addEventListener('click', chefDeleteSelectedBatch);

        var dots = document.querySelectorAll('.chef-theme-dot');
        for (var i = 0; i < dots.length; i++) {
            (function(dot) {
                dot.addEventListener('click', function() {
                    setTheme(dot.getAttribute('data-theme'));
                });
            })(dots[i]);
        }

        document.addEventListener('click', function(e) {
            var popover = document.getElementById('chefSettingsPopover');
            var settingsBtn = document.getElementById('chefSettingsBtn');
            if (popover && popover.classList.contains('show')) {
                if (!popover.contains(e.target) && !settingsBtn.contains(e.target)) {
                    popover.classList.remove('show');
                }
            }
        });

        loadSessions();
    }

    /* ========== 强制覆盖头像颜色 (优化版 - 只处理新元素) ========== */
    var processedAvatars = new WeakSet();
    
    // 缓存计算值，避免每次都调用 getComputedStyle
    var CACHED_gradient_primary = null;
    var CACHED_accent = null;
    
    function getCachedGradientPrimary() {
        if (!CACHED_gradient_primary) {
            CACHED_gradient_primary = getComputedStyle(document.documentElement).getPropertyValue('--gradient-primary').trim() || 'linear-gradient(135deg, #7B9080, #9CAF9A)';
        }
        return CACHED_gradient_primary;
    }
    
    function getCachedAccent() {
        if (!CACHED_accent) {
            CACHED_accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#9CAF9A';
        }
        return CACHED_accent;
    }
    
    // 主题变化时清除缓存
    document.addEventListener('themechange', function() {
        CACHED_gradient_primary = null;
        CACHED_accent = null;
    });
    
    function forceOverrideAvatarColors() {
        var gradientPrimary = getCachedGradientPrimary();
        var accentColor = getCachedAccent();
        
        // 助手头像 - 批量处理
        var orangeGradient = document.querySelectorAll('[class*="from-orange-400"], [class*="from-orange-500"]');
        for (var i = 0; i < orangeGradient.length; i++) {
            if (!processedAvatars.has(orangeGradient[i])) {
                orangeGradient[i].style.setProperty('background', gradientPrimary, 'important');
                orangeGradient[i].style.setProperty('background-image', gradientPrimary, 'important');
                processedAvatars.add(orangeGradient[i]);
            }
        }

        // 用户头像 - 批量处理
        var blueGradient = document.querySelectorAll('[class*="from-blue-400"], [class*="from-blue-500"]');
        for (var j = 0; j < blueGradient.length; j++) {
            if (!processedAvatars.has(blueGradient[j])) {
                blueGradient[j].style.setProperty('background', accentColor, 'important');
                blueGradient[j].style.setProperty('background-image', accentColor, 'important');
                processedAvatars.add(blueGradient[j]);
            }
        }
    }

    // 修复图片尺寸 (优化版 - 只处理新图片)
    var processedImages = new WeakSet();
    
    function fixImageSizes() {
        var chatContainer = document.querySelector('.relative.flex.flex-col.min-h-screen.max-w-4xl');
        if (!chatContainer) return;
        
        var images = chatContainer.querySelectorAll('img');
        for (var i = 0; i < images.length; i++) {
            var img = images[i];
            if (processedImages.has(img)) continue;
            
            // 确保图片不超出容器
            img.style.setProperty('max-width', '100%', 'important');
            img.style.setProperty('max-height', '380px', 'important');
            img.style.setProperty('width', 'auto', 'important');
            img.style.setProperty('height', 'auto', 'important');
            img.style.setProperty('object-fit', 'contain', 'important');
            img.style.setProperty('border-radius', '12px', 'important');
            img.style.setProperty('display', 'block', 'important');
            
            // 修复父容器 - 如果父容器有 overflow-hidden，可能会裁剪图片
            var parent = img.parentElement;
            while (parent && parent !== chatContainer) {
                if (parent.classList.contains('overflow-hidden')) {
                    parent.style.setProperty('overflow', 'visible', 'important');
                }
                parent = parent.parentElement;
            }
            
            processedImages.add(img);
        }
    }

    // 使用 requestAnimationFrame 节流的 MutationObserver (优化版)
    var pendingUpdate = false;
    var updateTimer = null;
    
    function scheduleUpdate() {
        if (pendingUpdate) return;
        pendingUpdate = true;
        requestAnimationFrame(function() {
            pendingUpdate = false;
            // 只处理头像和图片，不做额外 DOM 查询
            forceOverrideAvatarColors();
            fixImageSizes();
        });
    }
    
    // 使用更高效的节流 - 最多每 300ms 执行一次
    var lastUpdateTime = 0;
    var THROTTLE_MS = 300;
    
    function throttledUpdate() {
        var now = Date.now();
        if (now - lastUpdateTime < THROTTLE_MS) return;
        lastUpdateTime = now;
        scheduleUpdate();
    }

    var avatarObserver = new MutationObserver(function(mutations) {
        // 只在有实际元素节点添加时才更新
        var hasElementChanges = false;
        for (var i = 0; i < mutations.length; i++) {
            var added = mutations[i].addedNodes;
            for (var j = 0; j < added.length; j++) {
                if (added[j].nodeType === 1) {
                    // 检查是否是我们关心的元素类型
                    var tag = added[j].tagName;
                    if (tag === 'DIV' || tag === 'IMG' || tag === 'SECTION' || tag === 'ARTICLE') {
                        hasElementChanges = true;
                        break;
                    }
                }
            }
            if (hasElementChanges) break;
        }
        if (hasElementChanges) {
            throttledUpdate();
        }
    });

    function startAvatarObserver() {
        // 只监听聊天容器，不监听整个 body
        var chatContainer = document.querySelector('.relative.flex.flex-col.min-h-screen.max-w-4xl');
        if (chatContainer) {
            avatarObserver.observe(chatContainer, {
                childList: true,
                subtree: true
            });
        } else {
            // 容器不存在时退回到监听 body，但使用更严格的过滤
            avatarObserver.observe(document.body, {
                childList: true,
                subtree: true
            });
        }
    }

    function init() {
        applySavedTheme();
        buildSidebar();
        forceOverrideAvatarColors();
        fixImageSizes();
        startAvatarObserver();
        setupChatFallback();

        // 加载当前会话的历史消息
        var currentThreadId = getCurrentThreadId();
        if (currentThreadId) {
            setTimeout(function() {
                loadSessionMessages(currentThreadId);
            }, 500);
        }

        // 减少初始轮询次数
        setTimeout(scheduleUpdate, 800);
        setTimeout(scheduleUpdate, 2500);
    }

    /* ========== 聊天回退功能（当 React 无法 hydrate 时使用） ========== */
    function setupChatFallback() {
        var textarea = document.querySelector('textarea[placeholder*="食材"]');
        var sendBtn = document.querySelector('button[disabled]');
        var chatArea = document.querySelector('.flex-1.overflow-y-auto');

        // 如果找到发送按钮且处于 disabled 状态，说明 React 未 hydrate
        if (!sendBtn || !sendBtn.hasAttribute('disabled')) {
            // React 已正常 hydrate，不需要回退
            return;
        }

        // 确保 thread_id 存在
        var threadId = getCurrentThreadId();
        if (!threadId) {
            // 自动创建会话
            fetch('/api/v1/sessions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_id: CHEF_USER_ID,
                    biz_type: CHEF_BIZ_TYPE,
                    name: 'AI 私厨会话 ' + new Date().toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'})
                })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.thread_id) {
                    setCurrentThreadId(data.thread_id);
                }
            });
        }

        // 启用发送按钮
        sendBtn.removeAttribute('disabled');

        // 输入框事件 - 启用/禁用发送按钮
        if (textarea) {
            textarea.addEventListener('input', function() {
                if (this.value.trim()) {
                    sendBtn.removeAttribute('disabled');
                } else {
                    sendBtn.setAttribute('disabled', '');
                }
            });

            // 回车发送（Shift+Enter换行）
            textarea.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                }
            });
        }

        // 发送按钮点击
        sendBtn.addEventListener('click', function(e) {
            e.preventDefault();
            sendMessage();
        });

        // 处理头部"新建会话"按钮
        var headerNewBtn = null;
        var headerBtns = document.querySelectorAll('header button');
        for (var i = 0; i < headerBtns.length; i++) {
            if (headerBtns[i].textContent.indexOf('新建会话') >= 0) {
                headerNewBtn = headerBtns[i];
                break;
            }
        }
        if (headerNewBtn) {
            headerNewBtn.addEventListener('click', function(e) {
                e.preventDefault();
                createNewSession();
            });
        }

        // 处理图片上传按钮（优先找 Next.js 原生的 input[type=file]，再回退到通用的 SVG 图标按钮）
        var fileInput = document.querySelector('input[type="file"]');
        var fileBtn = null;
        if (fileInput) {
            // 找到离 fileInput 最近、且作为其控制按钮的可点击元素：
            // 策略1：fileInput 的前一个兄弟节点；策略2：所有包含 SVG 的按钮中，其父包含 fileInput
            var candidates = [];
            var parent = fileInput.parentElement;
            for (var i = 0; i < 5 && parent; i++) {
                candidates = parent.querySelectorAll('button, [role="button"], [data-testid*="upload"]');
                if (candidates.length) break;
                parent = parent.parentElement;
            }
            for (var ci = 0; ci < candidates.length; ci++) {
                var txt = (candidates[ci].textContent || '').trim();
                if (candidates[ci].querySelector('svg') || txt.indexOf('上传') >= 0 || txt.indexOf('图片') >= 0) {
                    fileBtn = candidates[ci];
                    break;
                }
            }
        }
        if (!fileBtn) {
            // 兜底：通过 class 猜
            fileBtn = document.querySelector('button.p-2\\.5.text-gray-500') || document.querySelector('button[aria-label*="upload" i]');
        }
        if (fileBtn && fileInput) {
            fileBtn.addEventListener('click', function(e) {
                e.preventDefault();
                fileInput.click();
            });
            fileInput.addEventListener('change', function() {
                if (this.files && this.files[0]) {
                    var file = this.files[0];
                    var reader = new FileReader();
                    reader.onload = function(ev) {
                        var dataUrl = ev.target.result;
                        // 客户端压缩图片：如果图片大于 500KB，压缩到 500KB 以内
                        compressImageIfNeeded(dataUrl, file, function(compressedUrl) {
                            window.__chefUploadedImage = compressedUrl;
                            if (textarea) {
                                textarea.placeholder = '图片已上传，请描述你想要的菜谱...';
                            }
                        });
                    };
                    reader.readAsDataURL(file);
                }
            });
        }

        // 客户端图片压缩函数
        function compressImageIfNeeded(dataUrl, file, callback) {
            // 估算 data URL 大小（base64 比原始大 33%）
            var estimatedSize = Math.round((dataUrl.length - 'data:image/jpeg;base64,'.length) * 3 / 4);
            var MAX_SIZE = 500 * 1024; // 500KB
            
            if (estimatedSize <= MAX_SIZE) {
                callback(dataUrl);
                return;
            }
            
            // 压缩图片
            var img = new Image();
            img.onload = function() {
                var canvas = document.createElement('canvas');
                var ctx = canvas.getContext('2d');
                
                // 如果图片太大，先缩放
                var maxDim = 1200;
                var w = img.width;
                var h = img.height;
                
                if (w > maxDim || h > maxDim) {
                    if (w > h) {
                        h = Math.round(h * maxDim / w);
                        w = maxDim;
                    } else {
                        w = Math.round(w * maxDim / h);
                        h = maxDim;
                    }
                }
                
                canvas.width = w;
                canvas.height = h;
                ctx.drawImage(img, 0, 0, w, h);
                
                // 降低质量直到文件大小足够小
                var quality = 0.8;
                var result = canvas.toDataURL('image/jpeg', quality);
                
                // 尝试降低质量
                var compressLoop = function() {
                    var size = Math.round((result.length - 'data:image/jpeg;base64,'.length) * 3 / 4);
                    if (size <= MAX_SIZE || quality < 0.3) {
                        callback(result);
                        return;
                    }
                    quality -= 0.1;
                    result = canvas.toDataURL('image/jpeg', quality);
                    compressLoop();
                };
                compressLoop();
            };
            img.onerror = function() {
                callback(dataUrl); // 失败则使用原图
            };
            img.src = dataUrl;
        }

        var isStreaming = false;

        function sendMessage() {
            if (isStreaming) return;
            var text = textarea ? textarea.value.trim() : '';
            // 取图片策略（优先级）：
            // 1) fallback 自己通过 fileInput 上传并保存在 window.__chefUploadedImage 的 data URI
            // 2) 从 chatArea 中最近的用户消息预览图里拿 <img src>（React 流程上传后会在这里渲染出来）
            // 3) 从输入框周边的预览区找 img
            var image = window.__chefUploadedImage || '';
            if (!image && chatArea) {
                var userImgs = chatArea.querySelectorAll('.chef-msg-user img, .chef-msg-user [class*="image"] img, img');
                for (var k = userImgs.length - 1; k >= 0; k--) {
                    var src = userImgs[k].src || userImgs[k].getAttribute('src');
                    if (src && src.indexOf('blob:') !== 0) {
                        image = src;
                        break;
                    }
                }
            }
            // 兜底：从整个页面的最近 OSS 图片中取第一个
            if (!image) {
                var allImgs = document.querySelectorAll('img[src*="aliyuncs.com"], img[src^="https://tmp7934"]');
                if (allImgs && allImgs.length) image = allImgs[allImgs.length - 1].src;
            }
            if (!text && !image) return;

            var tid = getCurrentThreadId();
            if (!tid) {
                alert('会话创建中，请稍后再试');
                return;
            }

            // 清空输入框
            if (textarea) textarea.value = '';
            window.__chefUploadedImage = null;
            if (textarea) textarea.placeholder = '描述你有的食材...';
            if (sendBtn) sendBtn.setAttribute('disabled', '');

            // 渲染用户消息
            appendMessage('user', text, image);

            // 立即创建 assistant 消息容器（立刻显示，不再等"占位卡→正式卡"切换），
            // 流式过程中每 150ms 重新渲染一次当前的"纯文字结构 markdown"（不跑徽章/编号/图片后处理，
            // 避免半成品格式抖动），用户能亲眼看到文字逐段/逐字出现，感觉"速度快"。
            // 最终一次性排版（徽章+双图+编号校正）只在 __REPLACE_FULL__ 或 流结束 done 时执行。
            var assistantEl = document.createElement('div');
            assistantEl.className = 'chef-msg chef-msg-assistant';
            assistantEl.innerHTML =
                '<div class="chef-msg-avatar"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21a1 1 0 0 0 1-1v-5.35c0-.457.316-.844.727-1.041a4 4 0 0 0-2.134-7.589 5 5 0 0 0-9.186 0 4 4 0 0 0-2.134 7.588c.411.198.727.585.727 1.041V20a1 1 0 0 0 1 1Z"/><path d="M6 17h12"/></svg></div>' +
                '<div class="chef-msg-content"></div>';
            if (chatArea) {
                chatArea.appendChild(assistantEl);
                chatArea.scrollTop = chatArea.scrollHeight;
            }
            var contentEl = assistantEl.querySelector('.chef-msg-content');
            var fullText = '';  // 在外部定义 fullText，供内部函数使用
            var renderTimer = null;
            var pendingRender = false;
            var isFirstChunk = true;
            
            // 流式阶段：使用 textContent 显示原始文本，保留所有换行
            function doRenderStreaming() {
                if (!contentEl) return;
                // 思考过程模式：灰色小字展示流式内容
                contentEl.textContent = fullText;
                contentEl.classList.add('chef-thinking');
                contentEl.style.whiteSpace = 'pre-wrap';
                contentEl.style.fontSize = '';
                contentEl.style.lineHeight = '';
                if (chatArea) chatArea.scrollTop = chatArea.scrollHeight;
            }
            
            // 最终阶段：使用完整 markdown 渲染，移除思考样式
            function renderFinal() {
                if (renderTimer) { clearTimeout(renderTimer); renderTimer = null; pendingRender = false; }
                if (!contentEl || !fullText) return;
                try {
                    // 移除思考模式样式
                    contentEl.classList.remove('chef-thinking');
                    contentEl.style.whiteSpace = '';
                    // 使用完整 markdown 渲染
                    contentEl.innerHTML = chefSimpleMarkdown(fullText);
                    // 应用卡片徽章
                    __chefApplyCardBadges(contentEl);
                } catch(e) {
                    // 失败则回退到纯文本
                    contentEl.classList.remove('chef-thinking');
                    contentEl.textContent = fullText;
                    contentEl.style.whiteSpace = 'pre-wrap';
                }
                if (chatArea) chatArea.scrollTop = chatArea.scrollHeight;
            }
            
            function scheduleRenderStreaming(immediate) {
                if (immediate) {
                    if (renderTimer) { clearTimeout(renderTimer); renderTimer = null; }
                    doRenderStreaming();
                    return;
                }
                if (renderTimer) {
                    pendingRender = true;
                    return;
                }
                pendingRender = false;
                renderTimer = setTimeout(function() {
                    renderTimer = null;
                    var needAgain = pendingRender;
                    pendingRender = false;
                    doRenderStreaming();
                    if (needAgain) scheduleRenderStreaming(false);
                }, 50);  // 50ms 节流，平衡流畅度
            }

            isStreaming = true;

            // 调用流式 API：字段名必须与后端 ChatRequest 对齐，这里传 image_url（主字段）和 image（兼容字段）双保险
            fetch('/api/v1/chat/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: text,
                    image_url: image,
                    image: image,
                    thread_id: tid
                })
            })
            .then(function(response) {
                if (!response.ok) throw new Error('API错误: ' + response.status);
                var reader = response.body.getReader();
                var decoder = new TextDecoder();
                var buffer = '';
                fullText = '';  // 使用外部已声明的变量
                var sawFirstRealChunk = false;

                function readChunk() {
                    reader.read().then(function(result) {
                        if (result.done) {
                            isStreaming = false;
                            if (sendBtn) sendBtn.removeAttribute('disabled');
                            if (fullText && fullText.replace(/\s/g,'') !== '') {
                                renderFinal();
                            }
                            return;
                        }
                        buffer += decoder.decode(result.value, {stream: true});
                        
                        // SSE 解析：按 \n\n 分割消息
                        var messages = buffer.split('\n\n');
                        buffer = messages.pop(); // 保留不完整的消息
                        
                        for (var mi = 0; mi < messages.length; mi++) {
                            var message = messages[mi].trim();
                            if (!message) continue;
                            
                            // 提取 data: 后面的内容
                            var payload = message;
                            if (payload.indexOf('data:') === 0) {
                                payload = payload.slice(5).trim();
                            }
                            if (!payload || payload === '[DONE]') continue;

                            // 还原转义字符（后端发送 \\n 实际表示换行）
                            payload = payload
                                .replace(/\\r\\n/g, '\n')
                                .replace(/\\n/g, '\n')
                                .replace(/\\t/g, '\t')
                                .replace(/\\"/g, '"')
                                .replace(/\\\\/g, '\\');

                            // 处理特殊指令
                            var REPLACE_MARK = '__REPLACE_FULL__:';
                            if (payload.indexOf(REPLACE_MARK) === 0) {
                                fullText = payload.slice(REPLACE_MARK.length);
                                renderFinal();
                                continue;
                            }

                            // 普通 chunk：累积 + 渲染
                            if (!sawFirstRealChunk) {
                                var visible = payload.replace(/[\u200B-\u200D\uFEFF]/g, '');
                                if (visible === '') {
                                    fullText += payload;
                                    continue;
                                }
                                sawFirstRealChunk = true;
                            }
                            fullText += payload;
                            // 首块立即渲染，后续节流渲染
                            scheduleRenderStreaming(isFirstChunk);
                            isFirstChunk = false;
                        }

                        readChunk();
                    }).catch(function(err) {
                        isStreaming = false;
                        if (sendBtn) sendBtn.removeAttribute('disabled');
                        appendMessage('assistant', '回复失败: ' + err.message);
                    });
                }
                readChunk();
            })
            .catch(function(err) {
                isStreaming = false;
                if (sendBtn) sendBtn.removeAttribute('disabled');
                appendMessage('assistant', '连接失败: ' + err.message);
            });
        }

        function appendMessage(role, text, image) {
            var msg = document.createElement('div');
            msg.className = role === 'user' ? 'chef-msg chef-msg-user' : 'chef-msg chef-msg-assistant';

            var avatar = role === 'user'
                ? '<div class="chef-msg-avatar chef-msg-avatar-user"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg></div>'
                : '<div class="chef-msg-avatar"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21a1 1 0 0 0 1-1v-5.35c0-.457.316-.844.727-1.041a4 4 0 0 0-2.134-7.589 5 5 0 0 0-9.186 0 4 4 0 0 0-2.134 7.588c.411.198.727.585.727 1.041V20a1 1 0 0 0 1 1Z"/><path d="M6 17h12"/></svg></div>';

            var content = '<div class="chef-msg-content">';
            if (image) {
                content += '<img src="' + image + '" style="max-width:200px;max-height:200px;border-radius:8px;margin-bottom:8px;display:block;">';
            }
            if (text) {
                if (role === 'assistant') {
                    // 助手消息：解析 Markdown，配合 CSS 卡片样式渲染
                    content += chefSimpleMarkdown(text);
                } else {
                    // 用户消息：保持纯文本转义，避免用户输入的 markdown 被当成指令
                    content += escapeHtml(text).replace(/\n/g, '<br>');
                }
            }
            content += '</div>';

            msg.innerHTML = avatar + content;
            // 调用统一卡片徽章后处理（JS 自动生成菜图/补emoji，与后端插图无缝融合）
            if (role === 'assistant') {
                var _contentEl = msg.querySelector('.chef-msg-content');
                if (_contentEl && typeof __chefApplyCardBadges === 'function') __chefApplyCardBadges(_contentEl);
                else if (_contentEl && window.__chefApplyCardBadges) window.__chefApplyCardBadges(_contentEl);
            }
            if (chatArea) {
                chatArea.appendChild(msg);
                chatArea.scrollTop = chatArea.scrollHeight;
            }
        }

        // 暴露给外部以便调试
        window.__chefSendMessage = sendMessage;
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
