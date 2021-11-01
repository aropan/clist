function update_sticky_header_problems_top() {
  $('tr.header-problems th').css('top', $('tr.header-row:first').height())
}

function color_by_group_score(attr = 'data-result') {
  var prev = null
  var idx = 0
  $('table.standings tr[data-result]').each(function(e) {
    var node = $(this)
    node.removeClass('odd')
    node.removeClass('even')
    node.removeClass('parity-border')
    var result = node.attr(attr)
    if (result != prev) {
      idx = 1 - idx
      if (prev != null) {
        node.addClass('parity-border')
      }
    }
    node.addClass(idx? 'odd' : 'even')
    prev = result
  })
}

function get_row_score(r) {
  return parseFloat(r.getAttribute('data-score'))
}

function get_row_penalty(r) {
  return parseFloat(r.getAttribute('data-penalty'))
}

function get_row_last(r) {
  return parseFloat(r.getAttribute('data-last'))
}

function cmp_row(a, b) {
  var a_score = get_row_score(a)
  var b_score = get_row_score(b)
  if (a_score != b_score) {
    return a_score > b_score? -1 : 1
  }
  var a_penalty = get_row_penalty(a)
  var b_penalty = get_row_penalty(b)
  if (a_penalty != b_penalty) {
    return a_penalty < b_penalty? -1 : 1
  }
  if (!a_penalty && !b_penalty) {
    return 0;
  }
  var a_last = get_row_last(a)
  var b_last = get_row_last(b)
  if (a_last != b_last) {
    return a_last < b_last? -1 : 1
  }
  return 0
}

function duration_to_text(duration) {
  var h = Math.floor(duration / 60 / 60)
  var m = Math.floor(duration / 60 % 60)
  var s = Math.floor(duration % 60)
  var ret = h + ':'
  if (m < 10) ret += '0'
  ret += m + ':'
  if (s < 10) ret += '0'
  ret += s
  return ret
}

var CURRENT_PERCENT = null
var TOOLTIP_TIMER = null
var TIMELINE_TIMER_ID = null
const RESET_TOOLTIP_DURATION = 3000

function step_timeline(multiplier = 1, stop = false) {
  CURRENT_PERCENT += multiplier * parseFloat($('#timeline-step').val())
  set_timeline(CURRENT_PERCENT)
  if (stop && TIMELINE_TIMER_ID || !stop && CURRENT_PERCENT >= contest_max_percent) {
    $('#play-timeline').click()
  }
}

function update_timeline_text(percent) {
  $('#timeline .progress-bar-success')[0].style.width = percent * 100 + '%'
  $('#timeline-text').text(duration_to_text(contest_duration * percent) + ' of ' + duration_to_text(contest_duration))
}

function shuffle_statistics_rows() {
  var rows = $('.stat-cell').toArray()
  shuffle(rows)
  $('table.standings tbody').html(rows)
}

function set_timeline(percent, duration = null) {
  if (duration == null) {
    duration = parseInt($('#timeline-duration').val())
  }
  if ($('.standings.invisible').length) {
    duration = 0
  }

  percent = Math.max(percent, 0)
  percent = Math.min(percent, contest_max_percent)
  update_timeline_text(percent)

  if (CURRENT_PERCENT == percent && (CURRENT_PERCENT <= 0 || CURRENT_PERCENT >= contest_max_percent)) {
    return
  }
  CURRENT_PERCENT = percent
  var current_time = contest_duration * percent

  if (TOOLTIP_TIMER) {
    clearTimeout(TOOLTIP_TIMER)
  }

  $('.stat-cell').each((_, e) => {
    score = 0
    if (contest_timeline['challenge_score']) {
      score += parseFloat($(e).attr('data-successful-challenge') || 0) * contest_timeline['challenge_score']['successful']
      score += parseFloat($(e).attr('data-unsuccessful-challenge') || 0) * contest_timeline['challenge_score']['unsuccessful']
    }
    $(e).attr('data-score', score)

    $(e).attr('data-penalty', 0)
    $(e).attr('data-more-penalty', 0)
    $(e).attr('data-last', 0)
  })


  problem_progress_stats = {}

  $('.stat-cell').css('transition', 'transform ' + duration + 'ms')

  $('.problem-cell.problem-cell-stat').each((_, e) => {
    var $e = $(e)
    var score = e.getAttribute('data-score')
    var penalty = e.getAttribute('data-penalty')
    var result = e.getAttribute('data-result')
    var more_penalty = e.getAttribute('data-more-penalty')
    var toggle_class = e.getAttribute('data-class')
    var problem_status = null

    var visible = true
    if (penalty) {
      var times = penalty.split(/[:\s]+/)
      var factors = contest_timeline['time_factor'][times.length]
      var time = times.reduce((r, t, i) => {
        if (t.endsWith('д.')) {
          t = parseInt(t) * 86400
        } else if (t.endsWith('ч.')) {
          t = parseInt(t) * 3600
        } else if (t.endsWith('м.')) {
          t = parseInt(t) * 60
        } else {
          t = parseInt(t) * factors[i]
        }
        return r + t
      }, 0)
      visible = time <= current_time
    } else {
      visible = CURRENT_PERCENT >= contest_max_percent
    }
    var pvisible = $e.attr('data-visible')
    $e.attr('data-visible', visible)

    if (visible) {
      $e.removeClass('result-hidden')
      problem_status = 'danger'
    } else {
      $e.addClass('result-hidden')
      problem_status = 'warning'
    }

    if (visible && (score.startsWith('+') || parseFloat(score) > 0)) {
      problem_status = $e.find('.par').length? 'info' : 'success'

      if (result.startsWith('+') && contest_timeline['penalty_more'] && !more_penalty) {
        more_penalty = result == '+'? 0 : parseInt(result)
      }

      var stat = $e.parent('.stat-cell')
      if (score.startsWith('+')) {
        if (penalty) {
          last = parseFloat(stat.attr('data-last'))
          stat.attr('data-last', Math.max(last, time))
          time += score == '+'? 0 : parseInt(score) * 1200
        }
        score = 1
      } else {
        score = parseFloat(score)
      }
      score += parseFloat(stat.attr('data-score'))
      stat.attr('data-score', score)
      if (penalty) {
        var rounding = contest_timeline['penalty_rounding'] || 'floor-minute'
        if (rounding == 'none') {
        } else if (rounding == 'floor-minute') {
          time = Math.floor(time / 60)
        } else {
          console.log('Unknown rounding:', rounding)
        }

        var agg = contest_timeline['penalty_aggregate'] || 'sum'
        if (agg == 'max') {
          time = Math.max(time, parseFloat(stat.attr('data-penalty')))
        } else if (agg == 'sum') {
          time += parseFloat(stat.attr('data-penalty'))
        } else {
          console.log('Unknown aggregate:', agg)
        }
        stat.attr('data-penalty', time)
      }

      if (more_penalty) {
        more_penalty = parseFloat(more_penalty) + parseFloat(stat.attr('data-more-penalty'))
        stat.attr('data-more-penalty', more_penalty)
      }
    }

    if (visible && pvisible === 'false') {
      highlight_element($e, duration, duration / 2, toggle_class)
    }

    if (problem_status) {
      var problem_key = e.getAttribute('data-problem-key')
      var problem_progress_stat = problem_progress_stats[problem_key] || (problem_progress_stats[problem_key] = {})
      problem_progress_stat[problem_status] = (parseInt(problem_progress_stat[problem_status]) || 0) + 1
    }
  })

  $('.stat-cell').each((_, e) => {
    $(e).find('.score-cell').text(e.getAttribute('data-score'))
    var format = contest_timeline['penalty_format'] || 1
    var penalty = parseFloat(e.getAttribute('data-penalty'))

    var more_penalty = parseFloat(e.getAttribute('data-more-penalty'))
    var more_penalty_factor = contest_timeline['penalty_more'] || 0
    var selector = contest_timeline['penalty_more_selector']
    if (selector) {
      $(e).find(selector).text(more_penalty)
    }
    if (more_penalty) {
      penalty += more_penalty * more_penalty_factor
      $(e).attr('data-penalty', penalty)
    }

    if (format == 1) {
    } else if (format == 2) {
      var ret = Math.floor(penalty / 60)
      var mod = penalty % 60
      ret += ':' + (mod < 10? '0' : '') + mod
      penalty = ret
    } else if (format == 3) {
      var ret = Math.floor(penalty / 60 / 60)
      var mod = Math.floor(penalty / 60 % 60)
      ret += ':' + (mod < 10? '0' : '') + mod
      var mod = penalty % 60
      ret += ':' + (mod < 10? '0' : '') + mod
      penalty = ret
    } else {
      console.log('Unknown format:', format)
    }

    var selector = contest_timeline['penalty_selector'] || '.addition-penalty-cell'
    $(e).find(selector).text(penalty)
  })

  var rows = $('.stat-cell')

  var total = rows.length
  if (total) {
    $('.problem-progress').each((_, e) => {
      $(e).parent('.problem-cell').find('.rej').removeClass('rej')
      var sum = 0
      var tooltip = ""
      var numbers = ['accepted', 'partial', 'hidden', 'wrong']
      var statuses = ['success', 'info', 'warning', 'danger']
      var problem_key = e.getAttribute('data-problem-key')
      var problem_progress_stat = problem_progress_stats[problem_key] || {}
      statuses.forEach((problem_status, i) => {
        var attr = 'data-' + problem_status
        var value = problem_progress_stat[problem_status] || 0
        var percent = value * 100 / total
        if (value) {
          tooltip += 'Number of ' + numbers[i] + ': ' + value + ' (' + percent.toFixed(2) + '%)<br/>'
        }
        sum += value
        $(e).find('.progress-bar.progress-bar-' + problem_status).css('width', percent.toFixed(3) + '%')
      })
      tooltip += 'Total: ' + total
      if (sum == 0) {
        $(e).remove()
      } else {
        if (problem_progress_stat['danger'] == sum) {
          $(e).parent('.problem-cell').find('span').addClass('rej')
        }
        $(e).attr('data-original-title', tooltip)
      }
    })
  }

  rows.sort(cmp_row)
  var first = null
  var last = null
  var current_top = $('table.standings thead')[0].offsetHeight

  rows.each((i, r) => {
    if (i == 0 || cmp_row(last, r) < 0) {
      if (first === null) {
        first = r
      }
      place = i
    }
    last = r

    var $r = $(r)
    $r.find('>.place-cell').attr('data-text', place + 1)

    var gap = (get_row_penalty(r) - get_row_penalty(first)) * 60 + (get_row_score(first) - get_row_score(r)) * current_time
    $r.find('>.gap-cell').attr('data-text', Math.round(gap / 60))

    $r.attr('data-translate-y', 'translateY(' + (r.offsetTop - current_top) + 'px)')
    $r.attr('data-scroll-top', current_top)
    current_top += r.offsetHeight
  })

  rows.find('>.place-cell').each((i, e) => { $(e).text($(e).attr('data-text')) })
  rows.find('>.gap-cell').each((i, e) => { $(e).text($(e).attr('data-text')) })
  rows.each((i, r) => { $r = $(r); $r.css('transform', $r.attr('data-translate-y')) })

  $('table.standings tbody').html(rows)
  color_by_group_score('data-score')

  scroll_to_find_me(duration, 0)

  setTimeout(() => { rows.css('transform', '') }, 1)

  TOOLTIP_TIMER = setTimeout(() => { toggle_tooltip_object($('table.standings [data-original-title]')) }, RESET_TOOLTIP_DURATION + duration)
}

function highlight_element(el, after = 1000, duration = 500, before_toggle_class = false, callback = function(){}) {
  if (!el.length) {
    return
  }
  var color = el.css('background-color')
  if (before_toggle_class) {
    el.removeClass(before_toggle_class)
  }
  setTimeout(function() {
    el.animate({'background-color': '#d0e3f7'}, duration, function() {
      el.animate({'background-color': color}, duration, function() {
        el.css('background', '')
        if (before_toggle_class) {
          el.addClass(before_toggle_class)
        }
        callback(el)
      })
    })
  }, after)
}

function show_timeline() {
  $('#timeline-buttons').toggleClass('hidden')
  $('#timeline').show()

  $('table.standings tr > *').classes(function(c, e) {
    if (c.endsWith('-medal')) {
      $(e).removeClass(c)
    }
  })
  $('table.standings .trophy').remove()

  $('table.standings .handle-cell .help-message').remove()
  $('table.standings .handle-cell.bg-success').removeClass('bg-success')

  $('.first-u-cell').remove()

  update_timeline_text(CURRENT_PERCENT)
}

function scroll_to_find_me(scroll_animate_time = 1000, color_animate_time = 500) {
  var el = $('.find-me-row')
  var find_me_pos = el.position()
  if (find_me_pos) {
    var table_inner_scroll = $('#table-inner-scroll')
    var table = table_inner_scroll.length? table_inner_scroll : $('html, body')
    var table_pos = table.position()
    var element_top = parseInt(el.attr('data-scroll-top')) + table_pos.top - table.scrollTop() || find_me_pos.top
    el.attr('data-scroll-top', '')
    var target = element_top - (table_pos.top + table.height() / 2)
    table.animate({scrollTop: target + table.scrollTop()}, scroll_animate_time)

    if (color_animate_time) {
      $('.find-me-row td').each(function() {
        highlight_element($(this), scroll_animate_time, color_animate_time)
      })
    }
  }
}

$(function() {
  CURRENT_PERCENT = contest_max_percent

  $('#timeline').click(function(e) {
    var percent = (e.pageX - $(this).offset().left) / $(this).width()
    if (TIMELINE_TIMER_ID) {
      $('#play-timeline').click()
    }
    set_timeline(percent)
  })

  var $tooltip = $('#timeline-tooltip')

  $('#timeline').mousemove(function(e) {
    var percent = (e.pageX - $(this).offset().left) / $(this).width()
    percent = Math.max(percent, 0)
    percent = Math.min(percent, 1)
    $tooltip.css({'left': e.pageX - $tooltip.width() / 2 - 5, 'top': e.pageY - $tooltip.height() - 5})
    $tooltip.show()
    $tooltip.text(duration_to_text(contest_duration * percent))
  })

  $('#timeline').mouseout(function(e) {
    $tooltip.hide()
  })

  $play_timeline = $('#play-timeline')

  function toggle_play_timeline() {
    $play_timeline.find('i').toggleClass('fa-play').toggleClass('fa-pause')
  }

  $play_timeline.click(function(e) {
    e.preventDefault()
    toggle_play_timeline()
    if (TIMELINE_TIMER_ID) {
      clearInterval(TIMELINE_TIMER_ID)
      TIMELINE_TIMER_ID = null
    } else if (CURRENT_PERCENT >= contest_max_percent) {
      setTimeout(toggle_play_timeline, 100)
    } else {
      TIMELINE_TIMER_ID = setInterval(step_timeline, $('#timeline-delay').val())
    }
  })

  $share_timeline = $('#share-timeline')

  $share_timeline.click(function(e) {
    e.preventDefault()
    url = window.location.href
    url = url.replace(/\btimeline=[^&]+&?/gi, '')
    url = url.replace(/\bt_[a-z]+=[^&]+&?/gi, '')
    url = url.replace(/[\?&]$/, '')
    url += (url.indexOf('?') == -1? '?' : '&') + 'timeline=' + duration_to_text(contest_duration * CURRENT_PERCENT)
    const keys = ['duration', 'step', 'delay']
    keys.forEach(function(k) { el = $('#timeline-' + k); url += '&t_' + k + '=' + el.val() })

    var dialog = bootbox.dialog({
      title: "Share standings url with timeline",
      message: '<div><input id="share-timeline-url" class="form-control"></intput></div>',
      buttons: {
        copy: {
          label: 'Copy',
          className: 'btn-default',
          callback: function () {
            $('#share-timeline-url').select()
            document.execCommand('copy')
          },
        },
        open: {
          label: 'Open',
          className: 'btn-default',
          callback: function (result) {
            var url = $('#share-timeline-url').val()
            window.location.href = url
          },
        },
      },
    })
    dialog.bind('shown.bs.modal', function() {
      $('#share-timeline-url').focus().val(url)
    })
  })

  $('#timeline-delay').change(function() {
    if (TIMELINE_TIMER_ID) {
      clearInterval(TIMELINE_TIMER_ID)
      TIMELINE_TIMER_ID = setInterval(step_timeline, $(this).val())
    }
  })

  $('#timeline-buttons button').keyup(function(event) {
    if (event.key == 'h') {
      $('#fast-backward-timeline').focus().click();
    } else if (event.key == 'j') {
      $('#step-forward-timeline').focus().click();
    } else if (event.key == 'k') {
      $('#step-backward-timeline').focus().click();
    } else if (event.key == 'l') {
      $('#fast-forward-timeline').focus().click();
    } else if (event.key == 'g') {
      $('#play-timeline').focus().click();
    }
    return false
  });
})
