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
const RESET_TOOLTIP_DURATION = 3000

function step_timeline() {
  if (CURRENT_PERCENT >= contest_max_percent) {
    return
  }
  CURRENT_PERCENT += parseFloat($('#timeline-step').val())
  set_timeline(CURRENT_PERCENT)
  if (CURRENT_PERCENT >= contest_max_percent) {
    $('#play-timeline').click()
  }
}

function update_timeline_text(percent) {
  $('#timeline .progress-bar-success')[0].style.width = percent * 100 + '%'
  $('#timeline-text').text(duration_to_text(contest_duration * percent) + ' of ' + duration_to_text(contest_duration))
}

function set_timeline(percent, duration = null) {
  if (duration == null) {
    duration = parseInt($('#timeline-duration').val())
  }

  if (TOOLTIP_TIMER) {
    clearTimeout(TOOLTIP_TIMER)
  }

  percent = Math.max(percent, 0)
  percent = Math.min(percent, contest_max_percent)
  update_timeline_text(percent)

  CURRENT_PERCENT = percent
  var current_time = contest_duration * percent

  $('.stat-cell').each((_, e) => {
    $(e).attr('data-score', 0)
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
      var times = penalty.split(':')
      var factors = contest_timeline['time_factor'][times.length]
      var time = times.reduce((r, t, i) => { return r + parseInt(t) * factors[i]; }, 0)
      visible = time <= current_time
    }
    var pvisible = $e.attr('data-visible')
    $e.attr('data-visible', visible)

    var problem_result = $e.find('>')
    if (visible) {
      problem_result.removeClass('hidden')
      $e.removeClass('problem-hidden')
      $e.addClass(toggle_class)
      problem_status = 'danger'
    } else {
      problem_result.addClass('hidden')
      $e.addClass('problem-hidden')
      $e.removeClass(toggle_class)
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
      highlight_element($e, duration, duration, toggle_class, function() {
        if (toggle_class && problem_result.hasClass('hidden')) {
          $e.removeClass(toggle_class)
        }
      })
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
    current_top += r.offsetHeight
  })

  rows.find('>.place-cell').each((i, e) => { $(e).text($(e).attr('data-text')) })
  rows.find('>.gap-cell').each((i, e) => { $(e).text($(e).attr('data-text')) })
  rows.each((i, r) => { $r = $(r); $r.css('transform', $r.attr('data-translate-y')) })

  $('table.standings tbody').html(rows)
  color_by_group_score('data-score')

  setTimeout(() => { rows.css('transform', '') }, 1)

  TOOLTIP_TIMER = setTimeout(() => { toggle_tooltip_object($('table.standings [data-original-title]')) }, RESET_TOOLTIP_DURATION + duration)
}

function highlight_element(el, after, duration, before_toggle_class = false, callback = function(){}) {
  var color = el.css('background-color')
  if (before_toggle_class) {
    el.toggleClass(before_toggle_class)
  }
  setTimeout(function() {
    el.animate({'background-color': '#d0e3f7'}, duration, function() {
      el.animate({'background-color': color}, duration, function() {
        el.css('background', '')
        if (before_toggle_class) {
          el.toggleClass(before_toggle_class)
        }
        callback()
      })
    })
  }, after)
}

function show_timeline() {
  $('#timeline-buttons').toggleClass('hidden')
  $('#timeline').show()

  $('table.standings td').classes(function(c, e) {
    if (c.endsWith('-medal')) {
      $(e).removeClass(c)
    }
  })

  $('.first-u-cell').remove()

  update_timeline_text(contest_max_percent)
  CURRENT_PERCENT = contest_max_percent
}

$(function() {
  $('#timeline').click(function(e) {
    var percent = (e.pageX - $(this).offset().left) / $(this).width()
    set_timeline(percent)
  })

  var $tooltip = $('#timeline-tooltip')

  $('#timeline').mousemove(function(e) {
    var percent = (e.pageX - $(this).offset().left) / $(this).width()
    $tooltip.css({'left': e.pageX - $tooltip.width() / 2 - 5, 'top': e.pageY - $tooltip.height() - 5})
    $tooltip.show()
    $tooltip.text(duration_to_text(contest_duration * percent))
  })

  $('#timeline').mouseout(function(e) {
    $tooltip.hide()
  })

  var timer_id = null
  $play_timeline = $('#play-timeline')

  function toggle_play_timeline() {
    $play_timeline.find('i').toggleClass('fa-play').toggleClass('fa-pause')
  }

  $play_timeline.click(function(e) {
    toggle_play_timeline()
    if (timer_id) {
      clearInterval(timer_id)
      timer_id = null
    } else if (CURRENT_PERCENT >= contest_max_percent) {
      setTimeout(toggle_play_timeline, 100)
    } else {
      timer_id = setInterval(step_timeline, $('#timeline-delay').val())
    }
    e.preventDefault()
  })

  $('#timeline-delay').change(function() {
    if (timer_id) {
      clearInterval(timer_id)
      timer_id = setInterval(step_timeline, $(this).val())
    }
  })
})
