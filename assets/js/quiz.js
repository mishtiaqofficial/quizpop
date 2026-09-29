/* QuizPop generic quiz engine.
   Reads window.QUIZ_DATA = {
     questions: [{ q, o:[4 options], s:[4 scores] } | { q, o:[4], correct: index } | { q, o:[4], cat:[4 keys] }],
     results:   [{ min,max,t,d } | { key,t,d }]
   }
   Modes: trivia (correct index) | category (cat keys) | score (s weights).
   Results are ALWAYS shown on-page — never gated behind any click. */
(function () {
  var D = window.QUIZ_DATA;
  if (!D) return;
  var qtext = document.getElementById('qtext'),
      opts  = document.getElementById('opts'),
      bar   = document.getElementById('bar'),
      nextBtn = document.getElementById('nextBtn'),
      quizSec = document.getElementById('quiz'),
      resSec  = document.getElementById('result');
  if (!qtext || !opts || !bar || !nextBtn || !quizSec || !resSec) return;

  var first = D.questions[0] || {};
  var mode = first.hasOwnProperty('correct') ? 'trivia'
           : first.hasOwnProperty('cat') ? 'category' : 'score';
  var qi = 0, score = 0, correct = 0, tally = {};

  function renderQ() {
    var Q = D.questions[qi];
    bar.style.width = (qi / D.questions.length * 100) + '%';
    qtext.textContent = (qi + 1) + '. ' + Q.q;
    opts.innerHTML = '';
    nextBtn.style.display = 'none';
    Q.o.forEach(function (t, i) {
      var b = document.createElement('button');
      b.className = 'opt';
      b.type = 'button';
      b.textContent = t;
      b.onclick = function () {
        if (mode === 'trivia') {
          if (i === Q.correct) { correct++; b.classList.add('correct'); }
          else { b.classList.add('wrong'); opts.children[Q.correct].classList.add('correct'); }
        } else if (mode === 'category') {
          var c = Q.cat[i];
          tally[c] = (tally[c] || 0) + 1;
          b.classList.add('correct');
        } else {
          score += Q.s[i];
          b.classList.add('correct');
        }
        Array.prototype.forEach.call(opts.children, function (x) { x.disabled = true; });
        nextBtn.style.display = 'inline-block';
      };
      opts.appendChild(b);
    });
    nextBtn.textContent = qi === D.questions.length - 1 ? 'See my result →' : 'Next →';
  }

  nextBtn.onclick = function () {
    qi++;
    if (qi < D.questions.length) { renderQ(); return; }
    quizSec.style.display = 'none';
    var r = null;
    if (mode === 'trivia') {
      r = D.results.find(function (x) { return correct >= x.min && correct <= x.max; });
    } else if (mode === 'category') {
      var top = Object.keys(tally).sort(function (a, b) { return tally[b] - tally[a]; })[0];
      r = D.results.find(function (x) { return x.key === top; });
    } else {
      r = D.results.find(function (x) { return score >= x.min && score <= x.max; });
    }
    if (!r) r = D.results[0];
    document.getElementById('rTitle').textContent = r.t;
    document.getElementById('rDesc').textContent = r.d;
    resSec.style.display = 'block';
    resSec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (window.gtag) gtag('event', 'quiz_completed', { quiz_mode: mode, value: mode === 'trivia' ? correct : score });
  };

  /* Share buttons — used by quiz pages via quizShare('x'|'fb'|'wa'|'copy') */
  window.quizShare = function (net) {
    var url = encodeURIComponent(location.href);
    var title = document.getElementById('rTitle');
    var txt = encodeURIComponent('I got: ' + (title ? title.textContent : document.title) + ' — what do you get?');
    var L = {
      x:  'https://twitter.com/intent/tweet?text=' + txt + '&url=' + url,
      fb: 'https://www.facebook.com/sharer/sharer.php?u=' + url,
      wa: 'https://wa.me/?text=' + txt + '%20' + url
    };
    if (net === 'copy') {
      if (navigator.clipboard) navigator.clipboard.writeText(location.href).then(function () { alert('Link copied!'); });
    } else if (L[net]) {
      window.open(L[net], '_blank', 'noopener');
    }
  };

  renderQ();
})();
