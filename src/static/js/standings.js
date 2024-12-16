function resize_window() {
  $(window).trigger('resize')
}

function update_sticky() {
  $('tr.header-problems').css('top', $('tr.header-row:first').height())

  var width = 0
  var seen = []
  $('tr .sticky-column').each(function() {
    var column = $(this).attr('data-sticky-column')
    if (seen[column]) {
      return
    }
    seen[column] = true
    $('tr .' + column).css('left', width)
    width += $(this).outerWidth()
  })
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

function get_row_place(r) {
  return r.getAttribute('data-place')
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
  var a_place = get_row_place(a)
  var b_place = get_row_place(b)
  if (a_place != b_place && (a_place == unspecified_place || b_place == unspecified_place)) {
    return b_place == unspecified_place? -1 : 1;
  }
  var a_score = get_row_score(a)
  var b_score = get_row_score(b)
  if (a_score != b_score) {
    return a_score > b_score? -1 : 1
  }
  if (!contest_timeline['no_penalty_time']) {
    var a_penalty = get_row_penalty(a)
    var b_penalty = get_row_penalty(b)
    if (a_penalty != b_penalty) {
      return a_penalty < b_penalty? -1 : 1
    }
  }
  var a_last = get_row_last(a)
  var b_last = get_row_last(b)
  if (a_last != b_last) {
    return a_last < b_last? -1 : 1
  }
  return 0
}

function duration_to_text(duration) {
  duration = Math.round(duration)
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
var TIMELINE_TIMER_ID = null
var TRANSFORM_TIMER_ID = null
var UNFREEZE_OPENING = new Map()
var UNFREEZE_ORDER = null
var UNFREEZE_SIZE = 0
var CLEAR_STARRED_UNFREEZED_TIMER_ID = null
var PROBLEM_PROGRESS_STATS = {}
var UPDATE_TIMELINE_TEXT_TIMER_ID = null
var UPDATE_CONTEST_TIME_PERCENTAGE_BY_VIRTUAL_START_TIMER_ID = null
var UNFREEZE_INDEX_UNDEF = -1
var ERASE_SWITCHER_SELECTOR = '.stat-cell:not(.virtual-start-statistic) .problem-cell[data-result-switcher]'

function freeze_percent() {
  return freeze_duration? freeze_duration / contest_duration : 0
}

function unfreeze_percent() {
  return 1 - freeze_percent()
}

function unfreeze_duration() {
  return Math.round(contest_duration * unfreeze_percent())
}

function unfreeze_is_active(percent) {
  return unfreezing && !with_virtual_start && freeze_percent() && unfreeze_percent() <= percent && percent < 1
}

function step_timeline(multiplier = 1, stop = false) {
  var prev_percent = CURRENT_PERCENT
  var next_percent = prev_percent + multiplier * parseFloat($('#timeline-step').val())

  if (unfreeze_is_active(next_percent) || unfreeze_is_active(CURRENT_PERCENT)) {
    var unfreeze_index = Math.max(0, CURRENT_PERCENT - unfreeze_percent()) / freeze_percent() * UNFREEZE_SIZE
    if (multiplier > 0) {
      unfreeze_index = Math.ceil(unfreeze_index) + 0.5
    } else if (multiplier < 0) {
      unfreeze_index = Math.floor(unfreeze_index) - 0.5
    }
    if (next_percent === Infinity) {
      next_percent = 1
    } else if (next_percent === -Infinity) {
      next_percent = 0
    } else {
      next_percent = unfreeze_index / UNFREEZE_SIZE * freeze_percent() + unfreeze_percent()
      next_percent = Math.max(next_percent, 0)
      next_percent = Math.min(next_percent, 1)
    }
  }

  if (unfreezing && Math.min(next_percent, CURRENT_PERCENT) < unfreeze_percent() && unfreeze_percent() < Math.max(next_percent, CURRENT_PERCENT)) {
    next_percent = unfreeze_percent()
  }

  if (stop && TIMELINE_TIMER_ID || !stop && CURRENT_PERCENT >= contest_time_percentage) {
    $('#play-timeline').click()
  }

  set_timeline(next_percent)

  if (!unfreezing && prev_percent >= 1 && next_percent >= 1 && freeze_duration) {
    $('#unfreezing-timeline').click()
  }
}

function update_timeline_text(percent = null) {
  percent = percent || CURRENT_PERCENT
  var unfreeze_start = Math.min(contest_time_percentage, unfreeze_percent())
  $('#timeline-progress-select').css('width', Math.min(percent, unfreeze_start) * 100 + '%')
  $('#timeline-progress-hidden').css('width', Math.max(unfreeze_start - percent, 0) * 100 + '%')
  $('#timeline-progress-freeze').css('width', Math.max(percent - unfreeze_start, 0) * 100 + '%')
  var freeze_hidden_percent = Math.min(Math.max(contest_time_percentage - Math.max(percent, unfreeze_start), 0), freeze_percent()) * 100
  $('#timeline-progress-freeze-hidden').css('width', freeze_hidden_percent + '%')
  var unparsed_percent = Math.min(1, ($.now() / 1000 - contest_start_timestamp) / contest_duration)
  $('#timeline-progress-unparsed').css('width', (unparsed_percent - contest_time_percentage) * 100 + '%')

  if (unfreeze_is_active(percent)) {
    var value = (percent - unfreeze_percent()) / freeze_percent() * 100
    $('#timeline-text').text(value.toFixed(2) + '%')
  } else {
    $('#timeline-text').text(duration_to_text(contest_duration * percent) + ' of ' + duration_to_text(contest_duration))
  }

  if (percent >= 1 && UPDATE_TIMELINE_TEXT_TIMER_ID) {
    clearInterval(UPDATE_TIMELINE_TEXT_TIMER_ID)
    UPDATE_TIMELINE_TEXT_TIMER_ID = null
  }
}

function set_contest_time_percentage(time_percentage) {
  if (CURRENT_PERCENT == contest_time_percentage) {
    CURRENT_PERCENT = time_percentage
  }
  contest_time_percentage = time_percentage
  update_timeline_text(CURRENT_PERCENT)
}

function shuffle_statistics_rows() {
  var rows = $('.stat-cell').toArray()
  shuffle(rows)
  $('table.standings tbody').html(rows)
}

function clear_data_stat_cell(e) {
  score = 0
  if (contest_timeline['challenge_score']) {
    score += parseFloat($(e).attr('data-successful-challenge') || 0) * contest_timeline['challenge_score']['successful']
    score += parseFloat($(e).attr('data-unsuccessful-challenge') || 0) * contest_timeline['challenge_score']['unsuccessful']
  }
  score += parseFloat($(e).attr('data-additional-score') || 0)
  $(e).attr('data-score', score)
  $(e).attr('data-penalty', 0)
  $(e).attr('data-more-penalty', 0)
  $(e).attr('data-last', 0)
}

function is_hidden(score) {
  return score.startsWith('?')
}

function is_solved(score) {
  return score.startsWith('+') || parseFloat(score) > 0
}

function process_problem_cell(element, current_time, unfreeze_index, percentage_filled, callback) {
  var stat = $(element)
  var score = element.getAttribute('data-score')
  var penalty = element.getAttribute('data-penalty')
  var penalty_in_seconds = element.getAttribute('data-penalty-in-seconds')
  var result = element.getAttribute('data-result')
  var more_penalty = element.getAttribute('data-more-penalty')
  var problem_key = element.getAttribute('data-problem-key')
  var problem_status = null
  var stat_cell = stat.parent('.stat-cell')
  var statistic_id = stat_cell.data('statistic-id')
  var unfreeze_open_index = UNFREEZE_OPENING.get(statistic_id + '_' + problem_key)
  var finished_unfreeze = unfreeze_index === UNFREEZE_INDEX_UNDEF && percentage_filled
  var unfreeze_open = unfreeze_open_index !== undefined && (finished_unfreeze || unfreeze_open_index < unfreeze_index)
  var is_virtual_start = stat_cell.hasClass('virtual-start-statistic')

  var statistic_submissions = submissions[statistic_id]
  var problem_submissions = false
  var problem_submission = false
  var is_final_submission = false

  if (statistic_submissions) {
    problem_submissions = submissions[statistic_id][problem_key]
    last_index = problem_submissions? problem_submissions.length - 1 : undefined
    if (problem_submissions && unfreezing && problem_submissions[last_index][0] > unfreeze_duration()) {
      problem_submission = problem_submissions[last_index]
      is_final_submission = true
    } else if (problem_submissions) {
      for (var i = 0; i < problem_submissions.length; i++) {
        if (problem_submissions[i][0] < current_time) {
          problem_submission = problem_submissions[i]
          is_final_submission = i == last_index
        } else {
          break
        }
      }
    }
  }

  var pvisible = stat.attr('data-visible')
  if (stat.attr('data-final') === 'false' || stat.hasClass('result-unfreeze')) {
    pvisible = 'false'
  } else if (stat.attr('data-final') === 'true' && !stat.hasClass('result-unfreeze')) {
    pvisible = 'true'
  }

  var visible = true
  var is_active_switcher = stat.attr('data-active-switcher')

  if (is_active_switcher) {
    if (problem_submission) {
      data_penalty = Math.floor(problem_submission[0] / 60)
      data_score = problem_submission[1]
      data_result = problem_submission[1]

      stat.attr('data-score-switcher', data_score)
      stat.attr('data-result-switcher', data_result)
      stat.attr('data-penalty-switcher', data_penalty)
      stat.attr('data-final-switcher', is_final_submission)
    }
    problem_submission = false
    problem_submissions = false
  }

  if (problem_submission) {
    penalty = String(problem_submission[0] / 60)
    data_penalty = Math.floor(problem_submission[0] / 60)
    time = problem_submission[0]
    score = problem_submission[1]
    result = problem_submission[1]
    attempt = problem_submission[2]
    visible = unfreezing || time <= current_time

    if (time > unfreeze_duration() && !unfreeze_open) {
      score = '?' + (attempt + is_solved(score))
    }

    var updated_submissions = (
      stat.attr('data-score') != score ||
      stat.attr('data-result') != result ||
      stat.attr('data-penalty') != penalty ||
      stat.attr('data-final') != is_final_submission
    )

    stat.attr('data-score', score)
    stat.attr('data-result', result)
    stat.attr('data-penalty', data_penalty)
    stat.attr('data-final', is_final_submission)
    if (updated_submissions) {
      update_score_penalty_result.call(stat, 'submission')
    }
  } else if (problem_submissions) {
    visible = false
  } else if (penalty) {
    var times = penalty.split(/[:\s]+/)
    if (times.length in contest_timeline['time_factor']) {
      var time = parse_factors_time(contest_timeline['time_factor'], penalty)
    } else if (penalty_in_seconds) {
      var time = parseFloat(penalty_in_seconds)
    } else {
      var time = 0
      console.log('Unknown problem time')
    }
    to_show = time <= current_time
    visible = unfreezing || to_show

    if (unfreezing || !is_virtual_start) {
      if (
        !unfreeze_open && time > unfreeze_duration() && !is_hidden(score) && !is_active_switcher ||
        !unfreeze_open && unfreezing && is_active_switcher
      ) {
        score = '?'
        visible = false
      }
      if (!with_virtual_start && to_show) {
        stat.addClass('result-question')
      } else {
        stat.removeClass('result-question')
      }
    }
  } else {
    visible = percentage_filled
  }

  var is_hidden_score = is_hidden(score)
  var is_solved_score = is_solved(score)

  if (unfreeze_open) {
    visible = true
  } else if (with_virtual_start && !is_virtual_start) {
    if (unfreeze_open_index !== undefined && unfreeze_index == UNFREEZE_INDEX_UNDEF) {
      visible = false
    } else if (!submissions && !is_solved_score) {
      visible = false
    }
  }

  stat.attr('data-visible', visible)

  if (visible) {
    stat.removeClass('result-hidden')
  } else {
    stat.addClass('result-hidden')
  }

  if (is_hidden_score || !visible) {
    stat.addClass('result-unfreeze')
  } else {
    stat.removeClass('result-unfreeze')
  }

  if (visible && is_solved_score) {
    problem_status = stat.find('.par').length? 'info' : 'success'

    if (result && result.startsWith('+') && contest_timeline['penalty_more'] && !more_penalty) {
      more_penalty = result == '+'? 0 : parseInt(result)
    }

    if (score.startsWith('+')) {
      if (penalty) {
        last = parseFloat(stat_cell.attr('data-last'))
        stat_cell.attr('data-last', Math.max(last, time))
        var attempt_penalty = contest_timeline['attempt_penalty']
        attempt_penalty = attempt_penalty === undefined? 1200 : attempt_penalty
        time += score == '+'? 0 : parseInt(score) * attempt_penalty
      }
      score = 1
    } else {
      score = parseFloat(score)
    }
    score += parseFloat(stat_cell.attr('data-score'))
    stat_cell.attr('data-score', score)
    if (penalty) {
      var agg = contest_timeline['penalty_aggregate'] || 'sum'
      if (agg == 'max') {
        time = Math.max(time, parseFloat(stat_cell.attr('data-penalty')))
      } else if (agg == 'sum') {
        time += parseFloat(stat_cell.attr('data-penalty'))
      } else {
        console.log('Unknown aggregate:', agg)
      }
      stat_cell.attr('data-penalty', time)
    }

    if (more_penalty) {
      more_penalty = parseFloat(more_penalty) + parseFloat(stat_cell.attr('data-more-penalty'))
      stat_cell.attr('data-more-penalty', more_penalty)
    }
  } else if (visible && is_hidden_score) {
    problem_status = 'warning'
  } else if (visible) {
    problem_status = 'danger'
  } else {
    problem_status = ''
  }

  if (callback !== null) {
    callback(element, visible, pvisible, problem_status)
  }
}

function process_stat_cell(element) {
  var stat_cell = $(element)
  var penalty = parseFloat(element.getAttribute('data-penalty'))
  var more_penalty = parseFloat(element.getAttribute('data-more-penalty'))
  var more_penalty_factor = contest_timeline['penalty_more'] || 0
  var penalty_more_selector = contest_timeline['penalty_more_selector']
  if (penalty_more_selector) {
    stat_cell.find(penalty_more_selector).text(more_penalty)
  }
  if (more_penalty) {
    penalty += more_penalty * more_penalty_factor
    stat_cell.attr('data-penalty', penalty)
  }
  var additional_penalty = parseFloat(element.getAttribute('data-additional-penalty'))
  if (additional_penalty) {
    penalty += additional_penalty
    stat_cell.attr('data-penalty', penalty)
  }
}

function clear_unfreeze() {
  unfreezing = false
  UNFREEZE_OPENING.clear()
  UNFREEZE_ORDER = []
  UNFREEZE_SIZE = 0
}

function toggle_unfreezing(btn) {
  btn = $(btn)
  if (!unfreezing) {
    prepare_unfreeze()
    set_timeline(unfreeze_percent())
    btn.addClass('active')
  } else {
    clear_unfreeze()
    set_timeline()
    btn.removeClass('active')
  }
  return false
}

function prepare_unfreeze() {
  clear_unfreeze()
  unfreezing = true

  var stat_cells = $('.stat-cell').clone()

  stat_cells.each((_, e) => { clear_data_stat_cell(e) })

  var current_time = unfreeze_duration()
  var problems_popularity = []
  stat_cells.find('.problem-cell.problem-cell-stat').each((_, e) => {
    var problem_key = $(e).attr('data-problem-key')
    problems_popularity[problem_key] = (problems_popularity[problem_key] || 0) + 1
    process_problem_cell(e, current_time, UNFREEZE_INDEX_UNDEF, false, null)
  })

  stat_cells.each((_, e) => { process_stat_cell(e) })

  stat_cells.sort(cmp_row)

  var candidates_selector = '.problem-cell.problem-cell-stat.result-unfreeze:not(.prepered-unfreeze)'

  var has_empty_penalty = false
  $(candidates_selector).each((_, e) => has_empty_penalty |= !$(e).attr('data-penalty'))

  for (var index = stat_cells.length - 1; index >= 0; index--) {
    var candidates, stat_cell
    while ((candidates = $(stat_cell = stat_cells[index]).find(candidates_selector)).length) {
      var min_penalty, max_popularity, problem_cell
      min_penalty = max_popularity = problem_cell = null
      candidates.each((_, e) => {
        var penalty = $(e).attr('data-penalty')
        var problem_key = $(e).attr('data-problem-key')
        var popularity = problems_popularity[problem_key]

        penalty = has_empty_penalty? Infinity : penalty.split(/[:\s]+/).reduce((r, t) => { return r * 60 + parseFloat(t) })

        if (!problem_cell || penalty < min_penalty || penalty == min_penalty && popularity > max_popularity) {
          problem_cell = e
          min_penalty = penalty
          max_popularity = popularity
        }
      })

      var opening = $(problem_cell)
      opening.addClass('prepered-unfreeze')
      var stat = opening.parent('.stat-cell')
      var statistic_id = stat.attr('data-statistic-id')
      var problem_key = opening.attr('data-problem-key')
      UNFREEZE_OPENING.set(statistic_id + '_' + problem_key, UNFREEZE_SIZE)
      UNFREEZE_ORDER.push({statistic_id, problem_key})
      UNFREEZE_SIZE += 1

      clear_data_stat_cell(stat_cell)
      $(stat_cell).find('.problem-cell.problem-cell-stat').each((_, e) => { process_problem_cell(e, current_time, UNFREEZE_SIZE, false, null) })
      process_stat_cell(stat_cell)

      for (var i = index; i > 0 && cmp_row(stat_cell, stat_cells[i - 1]) < 0; i--) {
        stat_cells[i] = stat_cells[i - 1]
        stat_cells[i - 1] = stat_cell
      }
    }
  }
  $('.prepered-unfreeze').removeClass('prepered-unfreeze')
}

function change_freeze_duration(select) {
  var value = select.value
  if (value.indexOf(':') !== -1) {
    var values = value.split(/[:\s]+/)
    freeze_duration = values.reduce((r, t) => { return r * 60 + parseFloat(t) })
  } else {
    freeze_duration = parseFloat(value) * contest_duration
  }
  if (unfreezing) {
    prepare_unfreeze()
  }
  set_timeline()
}

function clear_starred_unfreezed() {
  if (CLEAR_STARRED_UNFREEZED_TIMER_ID) {
    clearInterval(CLEAR_STARRED_UNFREEZED_TIMER_ID)
    CLEAR_STARRED_UNFREEZED_TIMER_ID = null
  }
  $('.starred.unfreezed').each((_, e) => { change_starring.call(e) })
  restarred()
}

function set_timeline(percent = null, duration = null, scroll_to_element = null) {
  if (duration == null) {
    duration = parseInt($('#timeline-duration').val())
  }
  if ($('.standings.invisible').length) {
    duration = 0
  }

  var percent_sign = 0
  if (percent == null) {
    percent = CURRENT_PERCENT
  } else {
    percent = Math.max(percent, 0)
    percent = Math.min(percent, contest_time_percentage)
    percent_sign = Math.sign(percent - CURRENT_PERCENT)
    CURRENT_PERCENT = percent
  }
  percentage_filled = with_virtual_start? percent >= 1 : percent >= contest_time_percentage
  update_timeline_text(percent)

  var current_time, unfreeze_index, highlight_problem_duration
  if (unfreeze_is_active(percent)) {
    current_time = unfreeze_duration()
    unfreeze_index = (percent - unfreeze_percent()) / freeze_percent() * UNFREEZE_SIZE
    highlight_problem_duration = 0
    $('table.standings').addClass('unfreezing')
  } else {
    current_time = Math.round(contest_duration * percent)
    unfreeze_index = UNFREEZE_INDEX_UNDEF
    highlight_problem_duration = duration
    $('table.standings').removeClass('unfreezing')
  }

  var intermediate = !percentage_filled || (!unfreezing && freeze_duration) || with_virtual_start
  if (intermediate) {
    $('table.standings').addClass('intermediate')
  } else {
    $('table.standings').removeClass('intermediate')
  }

  clear_starred_unfreezed()
  if (unfreeze_index != UNFREEZE_INDEX_UNDEF && scroll_to_element === null) {
    var target_index = Math.floor(unfreeze_index) + (percent_sign < 0? 1 : 0)
    if (0 <= target_index && target_index < UNFREEZE_SIZE) {
      var statistic_id = UNFREEZE_ORDER[target_index].statistic_id
      var statistic_element = $('.stat-cell[data-statistic-id="' + statistic_id + '"]')

      if (!scroll_to_element && $('.find-me-row').length == 0 && percent > unfreeze_percent()) {
        if (percent_sign < 0) {
          scroll_to_element = statistic_element
        } else {
          scroll_to_find_me(duration, 0, statistic_element)
        }
      }

      if (!statistic_element.hasClass('starred')) {
        change_starring.call(statistic_element)
        statistic_element.addClass('unfreezed')
        CLEAR_STARRED_UNFREEZED_TIMER_ID = setInterval(clear_starred_unfreezed, 10000)
      }
    }
  }

  $('.stat-cell').each((_, e) => { clear_data_stat_cell(e) })

  var problem_progress_stats = {}

  if (!with_detail) {
    $('.problem-cell').each(function() {
      var text_muted = $(this).find('.text-muted')
      if (!text_muted.length) {
        return
      }
      var text = text_muted.text()
      text_muted.remove()
      var result = $(this).children(':not(.hidden)')
      result.attr('title', text)
      result.attr('data-toggle', 'tooltip')
    })
    toggle_tooltip()
  }

  function process_problem_cell_callback(stat, visible, pvisible, problem_status) {
    stat = $(stat)
    var is_non_final = stat.attr('data-final') === 'false' || stat.hasClass('result-unfreeze')
    var toggle_class = stat.attr('data-active-switcher')? '' : stat.attr('data-class')
    var is_appearancing = (visible && !is_non_final) && pvisible === 'false'
    var is_disappearancing = (!visible || is_non_final) && pvisible !== 'false'

    if (toggle_class) {
      if (is_appearancing) {
        stat.addClass(toggle_class)
        highlight_element(stat, 0, duration / 2, toggle_class, function() { return stat.attr('data-visible') !== 'false' }, 0.25)
      }
      if (is_disappearancing) {
        stat.removeClass(toggle_class)
        // clear after highlight_element during fast timeline changing
        setTimeout(() => { stat.removeClass(toggle_class) }, duration)
      }
    }

    if (problem_status) {
      var problem_key = stat.attr('data-problem-key')
      var problem_progress_stat = problem_progress_stats[problem_key] || (problem_progress_stats[problem_key] = {})
      problem_progress_stat[problem_status] = (parseInt(problem_progress_stat[problem_status]) || 0) + 1
    }
  }

  $('.problem-cell.problem-cell-stat').each((_, e) => { process_problem_cell(e, current_time, unfreeze_index, percentage_filled, process_problem_cell_callback) })

  $('.stat-cell').each((_, e) => { process_stat_cell(e) })

  $('.stat-cell').each((_, e) => {
    var $e = $(e)
    var current_score = $e.find('.score-cell').text().trim()
    var new_score = e.getAttribute('data-score')
    if (score_precision !== undefined) {
      new_score = parseFloat(new_score).toFixed(score_precision)
    }
    $e.data('current-solving', new_score)
    $e.find('.score-cell').text(new_score)
    $e.css('z-index', current_score != new_score? '5' : '1')

    var penalty = parseFloat(e.getAttribute('data-penalty'))

    var rounding = contest_timeline['penalty_rounding'] || 'floor-minute'
    if (rounding == 'none') {
    } else if (rounding == 'floor-minute') {
      penalty = Math.floor(penalty / 60)
    } else if (rounding == 'floor-second') {
      penalty = Math.floor(penalty)
    } else {
      console.log('Unknown rounding:', rounding)
    }

    var format = contest_timeline['penalty_format'] || 1
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
    $e.data('current-penalty', penalty)
    $e.find(selector).text(penalty)

    var medals = ['gold', 'silver', 'bronze']
    medals.forEach(medal => {
      var selector = '.addition-n_' + medal + '_problems-cell'
      var element = $e.find(selector)
      if (element.length) {
        var n_medal = 0
        var selector = '.problem-cell-stat.' + medal + '-medal'
        var value = $e.find(selector).length
        n_medal += value
        var selector = '.problem-cell-stat[data-class="' + medal + '-medal"]:not(.result-hidden):not(' + selector + ')'
        var value = $e.find(selector).length
        n_medal += value
        element.html(n_medal || '&#183;')
      }
    })
  })

  var rows = $('.stat-cell')

  var total = rows.length
  if (total) {
    $('th.problem-cell[data-problem-key]').each((_, e) => {
      var problem_key = e.getAttribute('data-problem-key')
      var problem_cell = $(e)
      problem_cell.find('.rej').removeClass('rej')
      var problem_progress = $(e).find('.problem-progress')
      var sum = 0
      var tooltip = ""
      var numbers = ['accepted', 'partial', 'hidden', 'wrong']
      var statuses = ['success', 'info', 'warning', 'danger']
      var problem_progress_stat = problem_progress_stats[problem_key] || {}
      var previous_problem_progress_stat = PROBLEM_PROGRESS_STATS[problem_key] || {}
      var changed_statuses = []

      statuses.forEach((problem_status, i) => {
        var value = problem_progress_stat[problem_status] || 0
        var previous_value = previous_problem_progress_stat[problem_status] || 0

        if (value > previous_value && problem_status != 'warning') {
          changed_statuses.push(problem_status)
        }
        sum += value

        if (with_virtual_start && numbers[i] == 'hidden') {
          return;
        }

        var percent = value * 100 / total
        if (value) {
          tooltip += 'Number of ' + numbers[i] + ': ' + value + ' (' + percent.toFixed(2) + '%)<br/>'
        }

        problem_progress.find('.progress-bar.progress-bar-' + problem_status).css('width', percent.toFixed(3) + '%')
      })
      tooltip += 'Total: ' + total
      if (sum == 0) {
        problem_progress.hide()
      } else {
        problem_progress.show()
        if (problem_progress_stat['danger'] == sum) {
          problem_cell.find('span').addClass('rej')
        }
        if (problem_progress.attr('title')) {
          problem_progress.attr('title', tooltip)
        } else {
          problem_progress.attr('data-original-title', tooltip)
        }
      }
      if (duration && changed_statuses.length) {
        var problem_status = changed_statuses.length == 1? changed_statuses[0] : 'info'
        var problem_status_class = 'progress-bar-' + problem_status
        var el = problem_cell.children().first()
        el.addClass(problem_status_class, duration / 2, function() {
          el.removeClass(problem_status_class, duration / 2)
        })
      }
    })
    PROBLEM_PROGRESS_STATS = problem_progress_stats
  }

  var table_inner_scroll = $('#table-inner-scroll')
  var scroll_object = table_inner_scroll.length? table_inner_scroll : $('html, body')
  var table_top = $('table.standings').parent().offset().top
  var table_height = scroll_object.height()
  var thead_height = $('table.standings thead').height()
  var rows_top = table_top + thead_height

  var offset = rows_top
  rows.each((i, r) => {
    var $r = $(r)
    $r.attr('data-offset', offset)
    offset += r.offsetHeight
  })

  rows.sort(cmp_row)

  var first = null
  var last = null
  var current_top = rows_top
  var seen_first_u = new Map()
  var n_first_u = 0
  rows.each((i, r) => {
    if (i == 0 || cmp_row(last, r) < 0) {
      if (first === null) {
        first = r
      }
      place = i + 1
    }
    last = r

    var $r = $(r)
    var place_text = percentage_filled && standings_filtered? $r.attr('data-place') + ' (' + place + ')' : place;
    if (get_row_place(r) == unspecified_place) {
      place_text = unspecified_place
    }
    $r.data('current-place', place)
    $r.find('>.place-cell').attr('data-text', place_text)

    var gap = (get_row_penalty(r) - get_row_penalty(first)) + (get_row_score(first) - get_row_score(r)) * current_time
    $r.find('>.gap-cell').attr('data-text', Math.round(gap / 60))

    var first_u_cell = $r.find('>.first-u-cell >a[data-first-u-key]')
    if (first_u_cell.length) {
      var first_u_key = first_u_cell.attr('data-first-u-key')
      var first_u_quota = first_u_cell.attr('data-first-u-quota')
      seen_first_u.set(first_u_key, (seen_first_u.get(first_u_key) || 0) + 1)
      var in_quota = seen_first_u.get(first_u_key) <= first_u_quota
      n_first_u += in_quota
      var class_func = in_quota && (!n_highlight || n_first_u <= n_highlight)? 'removeClass' : 'addClass'
      first_u_cell[class_func]('out-of-quota')
      first_u_cell.attr('data-text', n_first_u)
    }

    var translation = $r.attr('data-offset') - current_top
    $r.removeAttr('data-offset')

    if ($r.hasClass('starred')) {
      var up = $r.offset().top - rows_top - parseFloat($r.css('top')) + thead_height
      var down = table_height - up - parseFloat($r.css('top')) - parseFloat($r.css('bottom')) - r.offsetHeight
      if (translation < -down) {
        translation = -down
      }
      if (translation > up) {
        translation = up
      }
    }

    $r.attr('data-translate-y', 'translateY(' + translation + 'px)')
    $r.attr('data-scroll-top', current_top)
    current_top += r.offsetHeight

    if (translation > 0 && !$r.css('z-index')) {
      $r.css('z-index', '3')
    }
  })


  var toggle_hidden_selectors = ['table.standings td .trophy', 'table.standings .medal-percentange']
  var toggle_hidden_selector = ''
  toggle_hidden_selectors.forEach((selector) => {
    if (toggle_hidden_selector) {
      toggle_hidden_selector += ','
    }
    toggle_hidden_selector += selector + (intermediate? ':not(.hidden)' : '.hidden')
  })
  if (toggle_hidden_selector) {
    var toggle_hidden_elements = $(toggle_hidden_selector)
    if (toggle_hidden_elements.length) {
      toggle_hidden_elements.toggleClass('hidden')
    }
  }

  rows.find('>.place-cell').each((i, e) => { $(e).text($(e).attr('data-text')) })
  rows.find('>.gap-cell').each((i, e) => { $(e).text($(e).attr('data-text')) })
  rows.find('>.first-u-cell >a[data-text]').each((i, e) => { $(e).text($(e).attr('data-text')) })

  var delay_duration = duration / 2
  clearInterval(TRANSFORM_TIMER_ID)

  restarred()

  TRANSFORM_TIMER_ID = setTimeout(() => {
      var transform_duration = duration - delay_duration

      rows.css('transition', 'transform ' + transform_duration + 'ms')
      rows.each((i, r) => { $r = $(r); $r.css('transform', $r.attr('data-translate-y')) })

      $('table.standings tbody').html(rows)
      color_by_group_score('data-score')
      $('.accepted-switcher').click(switcher_click)

      bind_starring()
      restarred()

      clear_tooltip()
      toggle_tooltip_object('table.standings [data-original-title]')

      scroll_to_find_me(transform_duration, 0, scroll_to_element)
      rows.css('transform', '')
    },
    delay_duration,
  )

  resize_window()
}

function highlight_element(el, after = 1000, duration = 500, before_toggle_class = false, callback = undefined, duration_ratio = 1.0) {
  if (!el.length) {
    return
  }
  var color = el.css('background-color')
  if (before_toggle_class) {
    el.removeClass(before_toggle_class)
  }
  setTimeout(function() {
    el.animate({'background-color': '#d0e3f7'}, duration * duration_ratio, function() {
      el.animate({'background-color': color}, duration * (2 - duration_ratio), function() {
        el.css('background', '')
        if (callback === undefined || callback(el) !== false) {
          el.addClass(before_toggle_class)
        }
      })
    })
  }, after)
}


SWITCHER_CLICK_WITHOUT_UPDATE = false


function parse_factors_time(timeline_factors, penalty) {
  var times = penalty.split(/[:\s]+/)
  if (times.length in timeline_factors) {
    var factors = timeline_factors[times.length]
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
    return time
  } else {
    return undefined
  }
}

function edit_active_switcher_click(event, element) {
  var stat = $(element).closest('.problem-cell')
  var score = stat.attr('data-score')
  var penalty = stat.attr('data-penalty')
  var x_pos = stat.offset().left + stat.outerWidth() / 2
  var y_pos = stat.offset().top + stat.outerHeight() / 2

  var dialog = bootbox.dialog({
    size: 'small',
    message:
      '<input placeholder="Result" type="text" class="form-control input-sm" value="' + score + '" name="result" autocomplete="off">' +
      '<input placeholder="Penalty" type="text" class="form-control input-sm" value="' + penalty + '" name="penalty" autocomplete="off">',
    buttons: {
      cancel: {
        label: 'Cancel',
        className: 'btn-default btn-xs',
      },
      confirm: {
        label: 'Ok',
        className: 'btn-primary btn-xs confirm-button',
        callback: function (message) {
          var result = $('.bootbox-body input[name="result"]').val()
          var penalty = $('.bootbox-body input[name="penalty"]').val()
          stat.attr('data-score', result)
          stat.attr('data-result', result)
          stat.attr('data-penalty', penalty)
          stat.find('.edit-score').text(result)
          stat.find('.edit-penalty').text(penalty)
          switcher_updated(stat)
        },
      },
    },
    closeButton: false,
    className: 'edit-active-switcher-bootbox',
  })

  dialog.on('shown.bs.modal', function() {
    var input = $('.bootbox-body input[name="result"]')
    input.focus()
    input[0].setSelectionRange(score.length, score.length)
  })

  dialog.init(function() {
    dialog.find('input').on('keypress', function(e) {
      if (e.which == 13) {
        e.preventDefault()
        dialog.find('.confirm-button').click()
      }
    })
  })

  $('.modal-dialog').css({
    'position': 'absolute',
    'left': x_pos,
    'top': y_pos,
    'width': '100px',
  })

  event.preventDefault()
  event.stopImmediatePropagation()
}

function switcher_updated(stat) {
  if (unfreezing) {
    prepare_unfreeze()
  }
  if (!SWITCHER_CLICK_WITHOUT_UPDATE) {
    var tr = stat.closest('tr')
    set_timeline(null, null, tr)

    if (tr.hasClass('virtual-start-statistic')) {
      $.ajax({
        type: 'POST',
        url: change_url,
        data: {
          pk: coder_pk,
          name: 'update-virtual-start-statistic',
          id: virtual_start_pk,
          problem: stat.data('problem-key'),
          result: stat.data('score'),
          time: stat.data('penalty'),
          penalty: tr.data('current-penalty'),
          solving: tr.data('current-solving'),
        },
        success: function(data) { $.notify(data.message, data.status) },
        error: log_ajax_error_callback,
      })
    }
  }
}

function has_penalty(result) {
  return result && result.startsWith('+') && result != '+'
}

function update_score_penalty_result(type) {
  var stat = $(this)
  var score = stat.attr('data-score')
  var penalty = stat.attr('data-penalty')
  var result = stat.attr('data-result')

  if (stat.attr('data-problem-full-score') && contest_timeline['penalty_score_more'] && has_penalty(result)) {
    score += ' ('  + parseInt(result) + ')'
  }
  if (contest_timeline['penalty_more'] && score != result && has_penalty(result)) {
    penalty += result
  }

  stat.children().addClass('hidden')

  if (type == 'switcher') {
    var edit_btn = '<span class="edit-active-switcher" onclick="edit_active_switcher_click(event, this)"><i class="fa-regular fa-pen-to-square"></i></span>'
    var edit_score = '<span class="edit-score">' + escape_html(score) + '</span>'
    var edit_penalty = '<span class="edit-penalty">' + escape_html(penalty) + '</span>'
    stat.prepend('<div class="swi">' + edit_score + edit_btn + '</div><small class="text-muted"><div>' + edit_penalty + '</div></small>')
  } else if (type == 'submission') {
    if (is_hidden(score)) {
      stat_class = 'hid'
    } else if (is_solved(score)) {
      stat_class = 'acc'
    } else {
      stat_class = 'rej'
    }
    stat.prepend('<div class="' + escape_html(stat_class) + '">' + escape_html(score) + '</div><small class="text-muted"><div>' + escape_html(penalty) + '</div></small>')
  }

  if (!stat.hasClass('problem-cell-stat')) {
    stat.addClass('problem-cell-stat')
    stat.addClass('problem-cell-stat-' + type)
  }
}

function n_switchers() {
  return $(ERASE_SWITCHER_SELECTOR).length
}

function switcher_click(event) {
  const hidden_regex = /^[-+0-9]+$/
  var stat = $(this)
  if (stat.attr('data-active-switcher') != 'true') {
    stat.attr('data-active-switcher', 'true')
    stat.attr('data-result-switcher', stat.attr('data-result') || '')
    stat.attr('data-score-switcher', stat.attr('data-score') || '')
    stat.attr('data-penalty-switcher', stat.attr('data-penalty') || '')

    var result = stat.attr('data-result')
    var penalty = Math.floor(contest_duration * CURRENT_PERCENT)
    var score = stat.attr('data-problem-full-score')
    if (contest_timeline['result_switcher_type'] == 'next_min') {
      var index = stat.parent().find('td').index(stat)
      var problem_cells = $('.stat-cell td:nth-of-type(' + (index + 1) + ')')
      var problem_results = problem_cells.map((_, e) => { return $(e).attr('data-result') })
      problem_results = problem_results.filter((_, r) => !!r)
      result = problem_results.length? Math.min(...problem_results) : problem_cells.length
      result = Math.max(0, result - 1)
      result = result.toString()
    } else if (!result) {
      result = '+'
    } else if (result.startsWith('-')) {
      result = '+' + result.substring(1)
    } else if (result.startsWith('?')) {
      result = result.substring(1)
      result = '+' + (hidden_regex.exec(result)? eval(result) - 1 || '' : '')
      penalty = parse_factors_time(contest_timeline['time_factor'], stat.attr('data-penalty')) || penalty
    }

    stat.attr('data-result', result)
    if (score) {
      if (contest_timeline['full_score_reduction_factor']) {
        score = Math.floor(score - score * contest_timeline['full_score_reduction_factor'] * penalty / 60)
      }
      if (contest_timeline['penalty_score_more'] && has_penalty(result)) {
        score -= contest_timeline['penalty_score_more'] * parseFloat(result)
      }
      if (contest_timeline['guaranteed_full_score_factor']) {
        score = Math.max(score, stat.attr('data-problem-full-score') * contest_timeline['guaranteed_full_score_factor'])
      }
    } else {
      score = result
    }
    stat.attr('data-score', score)

    var factors = contest_timeline['time_factor']
    if (factors) {
      var format = contest_timeline['penalty_format'] || 2
      penalty = factors[format].map(function(val, idx) {
        var ret = Math.floor(penalty / val)
        ret = idx? ret % (factors[format][idx - 1] / factors[format][idx]) : ret
        ret = idx && ret < 10? '0' + ret : ret
        return ret
      }).join(':')
    }
    stat.attr('data-penalty', penalty)

    update_score_penalty_result.call(stat, 'switcher')
  } else {
    if (stat.attr('data-result-switcher') === undefined) {
      stat.removeAttr('data-result')
      stat.removeAttr('data-score')
      stat.removeAttr('data-penalty')
      stat.removeAttr('data-final')
      stat.removeClass('problem-cell-stat')
    } else {
      stat.attr('data-result', stat.attr('data-result-switcher'))
      stat.attr('data-score', stat.attr('data-score-switcher'))
      stat.attr('data-penalty', stat.attr('data-penalty-switcher'))
      stat.attr('data-final', stat.attr('data-final-switcher'))
    }
    stat.removeAttr('data-active-switcher')
    stat.removeAttr('data-result-switcher')
    stat.removeAttr('data-score-switcher')
    stat.removeAttr('data-penalty-switcher')
    stat.removeAttr('data-final-switcher')
    stat.removeClass('result-hidden')
    stat.removeClass('result-unfreeze')
    stat.removeClass('result-question')

    stat.children().toggleClass('hidden')
    stat.children('.hidden').remove()

    if (stat.hasClass('problem-cell-stat-switcher')) {
      stat.removeClass('problem-cell-stat')
      stat.removeClass('problem-cell-stat-switcher')
    }
  }

  $('#erase-switchers-timeline').prop('disabled', n_switchers() == 0)
  switcher_updated(stat)
  clear_tooltip()

  event.preventDefault()
  event.stopImmediatePropagation()
}

function clear_extra_info_timeline() {
  $('table.standings tr > *').classes(function(c, e) {
    if ($(e).hasClass('problem-cell-stat')) {
      return
    }
    if (c.endsWith('-medal')) {
      $(e).removeClass(c)
    }
  })

  $('.other-problem-progress').remove()

  $('table.standings .handle-cell .help-message').remove()
  $('table.standings .handle-cell.bg-success').removeClass('bg-success')

  $('.stat-cell .problem-cell:not(.accepted-switcher)').addClass('accepted-switcher').click(switcher_click)

  update_sticky()
}

function show_timeline() {
  $('#timeline-buttons').toggleClass('hidden')
  $('#timeline').show()
  $('.standings .endless_container').remove()

  clear_extra_info_timeline()

  update_timeline_text(CURRENT_PERCENT)
  shown_timeline = true

  var input_timeline = $('[name="timeline"]')
  if (!input_timeline.length) {
    $('<input type="hidden" name="timeline" value=""/>').insertBefore('#show-timeline')
  }
  $('#show-timeline').attr('name', 'timeline').attr('value', 'off').attr('onclick', '').addClass('active')
  $('#step-backward-timeline').focus()

  if (CURRENT_PERCENT < 1) {
    var update_timeline_text_interval = Math.max(10, contest_duration / 1000)
    UPDATE_TIMELINE_TEXT_TIMER_ID = setInterval(update_timeline_text, update_timeline_text_interval * 1000)
  }

  restarred()
  resize_window()
}

function scroll_to_find_me(scroll_animate_time = 1000, color_animate_time = 500, el = null) {
  var el = el || $('.find-me-row')
  var find_me_pos = el.offset()
  if (find_me_pos) {
    var table_inner_scroll = $('#table-inner-scroll')
    var scroll_object = table_inner_scroll.length? table_inner_scroll : $('html, body')
    var table_top = $('table.standings').parent().offset().top
    var table_offset = $('table.standings').offset().top
    var screen_height = table_inner_scroll.length? table_inner_scroll.height() + 2 * table_offset : $(window).height()

    var element_top = parseInt(el.attr('data-scroll-top'))
    if (element_top) {
      el.attr('data-scroll-top', '')
      if (table_inner_scroll.length) {
        element_top -= table_top
        element_top += table_offset
      }
    } else {
      element_top = find_me_pos.top
    }

    var target = element_top - screen_height / 2
    scroll_object.stop()
    scroll_object.animate({scrollTop: target}, scroll_animate_time)

    if (color_animate_time) {
      $('.find-me-row td').each(function() {
        highlight_element($(this), scroll_animate_time, color_animate_time)
      })
    }
  }
}

function update_trophy_font_size() {
  height = Math.min(...$('.handle-cell .trophy-detail').closest('.handle-cell').map((_, e) => $(e).height())) / 2
  height = Math.max(14, height)
  $('.handle-cell .trophy-detail').each((_, e) => { $(e).css("font-size", height) })
}

$(function() {
  CURRENT_PERCENT = contest_time_percentage

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

    $tooltip.css({'left': e.pageX - $tooltip.width() / 2 - 5, 'top': e.pageY - $tooltip.height() + 30})
    $tooltip.show()

    if (unfreeze_is_active(percent)) {
      var value = (percent - unfreeze_percent()) / freeze_percent() * 100
      $tooltip.text(value.toFixed(2) + '%')
    } else {
      $tooltip.text(duration_to_text(contest_duration * percent))
    }
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
    } else if (CURRENT_PERCENT >= contest_time_percentage) {
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
    url = url.replace(/\bunfreezing\b&?/gi, '')
    url = url.replace(/[\?&]$/, '')
    url += (url.indexOf('?') == -1? '?' : '&') + 'timeline=' + duration_to_text(contest_duration * CURRENT_PERCENT)
    const keys = ['duration', 'step', 'delay', 'freeze']
    keys.forEach(function(k) { el = $('#timeline-' + k); url += '&t_' + k + '=' + el.val() })
    if (unfreezing) {
      url += '&unfreezing'
    }

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

  $('body').keyup(function(event) {
    if (event.isDefaultPrevented()) {
      return
    }

    var key = event.key.toLowerCase()
    if (key == 'escape') {
      $('.active#toggle-fullscreen').click()
    } else if (key == 'f') {
      $('#toggle-fullscreen').click()
    } else if (key == 't') {
      $('#show-timeline').click()
    } else if (shown_timeline) {
      if (key == 'h') {
        $('#fast-backward-timeline').focus().click()
      } else if (key == 'j') {
        $('#step-forward-timeline').focus().click()
      } else if (key == 'k') {
        $('#step-backward-timeline').focus().click()
      } else if (key == 'l') {
        $('#fast-forward-timeline').focus().click()
      } else if (key == 'g') {
        $('#play-timeline').focus().click()
      } else if (key == 'd') {
        $('#erase-switchers-timeline').focus().click()
      } else if (key == 'u') {
        $('#unfreezing-timeline').focus().click()
      }
    }

    event.preventDefault()
    return false
  });
})

/*
 * Starred
 */

function change_starring() {
  var element = $(this)
  if (!element.length) {
    return;
  }
  var stat = element.closest('.stat-cell')
  stat.toggleClass('info')
  stat.toggleClass('starred')
  stat.css('top', '').css('bottom', '')
}

function update_cookie_starring() {
  var stat = $(this).closest('.stat-cell')
  var statistic_id = stat.attr('data-statistic-id')
  var has_starred = stat.hasClass('starred')
  var starred = Cookies.get('starred', {path: starred_cookie_path})
  starred = !starred? Array() : starred.split(',')
  var index = starred.indexOf(statistic_id)
  if (has_starred && index == -1) {
    starred.push(statistic_id)
  } else if (!has_starred && index != -1) {
    starred.splice(index, 1)
  }
  starred = starred.join(',')
  Cookies.set('starred', starred, {expires: starred_cookie_expires, path: starred_cookie_path})
  update_unstar_hidden()
}

function update_unstar_hidden() {
  var starred = Cookies.get('starred', {path: starred_cookie_path})
  if (starred) {
    $('#unstar').removeClass('hidden')
  } else {
    $('#unstar').addClass('hidden')
  }
}

function starring() {
  change_starring.call(this)
  update_cookie_starring.call(this)
  restarred()
}

function bind_starring() {
  $('.stat-cell .star').unbind('click').click(starring)
}

function apply_starring() {
  bind_starring()

  var starred = Cookies.get('starred', {path: starred_cookie_path})
  starred = !starred? Array() : starred.split(',')
  starred.forEach(element => {
    change_starring.call($('.stat-cell.' + element + ':not(".starred") .star'))
  })

  restarred()

  update_unstar_hidden()
}

$(function() {
  $('#unstar_unpin').click(function() {
    $('.stat-cell.starred .star').click()
    Cookies.remove('starred', {path: starred_cookie_path})
    update_unstar_hidden()
  })

  $('#unstar_submissions').click(function() {
    var starred = Cookies.get('starred', {path: starred_cookie_path})
    var url = $(this).data('submissions-url')
    starred.split(',').forEach((element, index) => {
      url += (index? '&' : '?') + 'statistic=' + element
    })
    $(this).data('url', url)
    open_submissions(this)
  })

  var starred = Cookies.get('starred', {path: starred_cookie_path})
  if (starred) {
    Cookies.set('starred', starred, {expires: starred_cookie_expires, path: starred_cookie_path})
  }
})

/*
 * Standings live
 */

$(function() {
  const standings_socket = new WebSocket('wss://' + window.location.host + '/ws/contest/?pk=' + contest_pk)
  var n_messages = 0

  function clear_on_update_standings() {
    $('#parsed-time').remove()
  }

  function update_standings(data) {
    if (shown_timeline && !with_virtual_start) {
      clear_on_update_standings()
      set_contest_time_percentage(data.time_percentage)
    }
    var tr = $(data.rows).filter('tr')
    if (!tr.length) {
      return
    }
    var n_rows_msg = data.n_total && tr.length != data.n_total? tr.length + ' of ' + data.n_total : tr.length
    if (shown_timeline) {
      var standings = $('table.standings')
      tr.each(function() {
        var sid = $(this).attr('data-statistic-id')
        var orig = $('.' + sid)
        var replaced = orig.replaceWith(this).length
        if (!replaced && !standings_filtered) {
          standings.append(this)
        }
      })
      apply_starring()
      clear_extra_info_timeline()
      set_timeline()
      $.notify('updated ' + n_rows_msg + ' row(s)', 'success')
    } else {
      $.notify('updated ' + n_rows_msg + ' row(s), reload page to see', 'warn')
    }
  }

  standings_socket.onmessage = function(e) {
    const data = JSON.parse(e.data)
    if (data.type == 'standings') {
      update_standings(data)
    } else if (data.type == 'update_statistics') {
      update_statistics_log(data)
    }
    n_messages += 1
  }

  standings_socket.onclose = function(e) {
    if (n_messages) {
      $.notify('Socket closed unexpectedly', 'warn')
      $.notify('The page will be reloaded in 10 seconds', 'warn')
      setTimeout(() => { location.reload() }, 10000)
    }
  }
})


/*
 * Update statistics
 */

function replace_update_statistics_btn() {
  $('#update_statistics_btn').addClass('hidden')
  $('#show_update_statistics_log_btn').removeClass('hidden')
}

function show_update_statistics_log() {
  replace_update_statistics_btn()
  var log_modal = $('#update-statistics-log')
  log_modal.modal('show')

}

function spin_update_statistics_modal_btn(value) {
  var modal_btn = $('#modal-update-statistics-btn')
  if (value) {
    modal_btn.attr('disabled', true)
    modal_btn.find('i').addClass('fa-spin')
  } else {
    modal_btn.attr('disabled', false)
    modal_btn.find('i').removeClass('fa-spin')
  }
}

function update_statistics(e) {
  show_update_statistics_log()

  var icon = $(e).find('i')
  icon.addClass('fa-spin')
  var btn = icon.closest('a')
  btn.attr('disabled', 'disabled')
  $.ajax({
    type: 'POST',
    url: change_url,
    data: {
      pk: coder_pk,
      name: 'update-statistics',
      id: contest_pk,
    },
    error: log_ajax_error_callback,
    success: function() {
      $.notify('Queued update', 'success')
    },
    complete: function(jqXHR, textStatus) {
      icon.removeClass('fa-spin')
      btn.attr('disabled', false)
      spin_update_statistics_modal_btn(textStatus == 'success')
    },
  })
  event.preventDefault()
}

function update_statistics_log(data) {
  replace_update_statistics_btn()

  var log_output = $('#update-statistics-log-output')
  if (data.line) {
    var line = $('<span>').text(data.line + "\n")
    log_output.prepend(line)
  }
  if (data.progress !== undefined) {
    var progress_bar = $('#update-statistics-progress-bar')
    progress_bar.css('width', data.progress * 100 + '%')
    var progress_text = $('#update-statistics-progress-text')
    progress_text.text(data.desc)

    $('#update-statistics-progress').removeClass('hidden')
  }
  var is_done = data.done !== undefined
  if (is_done) {
    var line = $('<div class="horizontal-line"></div>')
    log_output.prepend(line)
    $('#update-statistics-progress').addClass('hidden')
  }
  spin_update_statistics_modal_btn(!is_done)
}


function open_submissions(btn) {
  var url = $(btn).data('url')
  if (shown_timeline && CURRENT_PERCENT < 1) {
    url += (url.includes('?') ? '&' : '?') + 'timeline=' + CURRENT_PERCENT
  }
  window.open(url, "_blank")
}

/*
 * View solution
 */

function viewSolution(a) {
  var href = $(a).attr('href')
  var solution_modal = $('#view-solution-modal')
  $('#view-solution-modal .modal-content').html('<div class="modal-body"><p><i class="fa fa-spin fa-circle-notch"></i> Loading...</p></div>')
  $('#view-solution-modal').modal('show')

  $.ajax({
    url: href,
    type: 'get',
    success: function(response) {
      $('#view-solution-modal .modal-content').html(response)
      if (solution_modal.hasClass('fullscreen')) {
          $('#toggle-fullscreen-modal').click()
          solution_modal.addClass('fullscreen')
      }
      document.querySelectorAll('pre code').forEach((block) => { hljs.highlightBlock(block) });
    },
    error: function(response) {
      bootbox.alert({
          title: response.responseText || response.statusText.toTitleCase(),
          message: 'You can check <a href="' + $(a).attr('data-url') + '">here</a>.',
          size: 'small'
      })
      $('#view-solution-modal').modal('hide')
    },
  })
  return false
}

/*
 * Press escape
 */

$(document).keydown(function(event) {
  if (event.keyCode == 27) {
    $('#view-solution-modal').modal('hide')
    $('#update-statistics-log').modal('hide')
  }
});


/*
 * Virtual start
 */

function click_finish_virtual_start(btn) {
  bootbox.confirm({
    size: 'small',
    message: 'Are you sure you want to finish virtual start?',
    callback: function(result) {
      if (!result) {
        return
      }
      $.ajax({
        type: 'POST',
        url: change_url,
        data: {
          pk: coder_pk,
          name: 'finish-virtual-start',
          id: virtual_start_pk,
        },
        error: log_ajax_error_callback,
        success: function() {
          finish_virtual_start()
          $(btn).remove()
        },
      })
    },
  })
}

function finish_virtual_start() {
  if (UPDATE_CONTEST_TIME_PERCENTAGE_BY_VIRTUAL_START_TIMER_ID) {
    clearInterval(UPDATE_CONTEST_TIME_PERCENTAGE_BY_VIRTUAL_START_TIMER_ID)
    UPDATE_CONTEST_TIME_PERCENTAGE_BY_VIRTUAL_START_TIMER_ID = null
  }

  set_contest_time_percentage(1)
  with_virtual_start = false

  var standings = $('table.standings')
  standings.removeClass('no-hints')
  standings.removeAttr('style').addClass('invisible')

  if (freeze_percent()) {
    prepare_unfreeze()
  }
  set_timeline(unfreeze_percent())
  visible_standings()
}

function update_contest_time_percentage_by_virtual_start() {
  var percentage = ($.now() / 1000 - contest_start_timestamp) / contest_duration
  percentage *= update_contest_time_percentage_multiplier
  percentage = Math.max(0, Math.min(1, percentage))
  set_contest_time_percentage(percentage)
  set_timeline()
  if (percentage >= 1 && UPDATE_CONTEST_TIME_PERCENTAGE_BY_VIRTUAL_START_TIMER_ID) {
    finish_virtual_start()
  }
}

function visible_standings() {
  $('.standings.invisible').removeClass('invisible').css({opacity: 0.0, visibility: "visible"}).animate({opacity: 1.0}, 1000);
  highlight_element($('.find-me-row'))
}

function setup_update_contest_time_percentage_by_virtual_start() {
  var val = parseFloat($('#timeline-follow').val())
  if (val) {
    UPDATE_CONTEST_TIME_PERCENTAGE_BY_VIRTUAL_START_TIMER_ID = setInterval(update_contest_time_percentage_by_virtual_start, val * 1000)
  }
}

function change_follow_interval() {
  if (UPDATE_CONTEST_TIME_PERCENTAGE_BY_VIRTUAL_START_TIMER_ID) {
    clearInterval(UPDATE_CONTEST_TIME_PERCENTAGE_BY_VIRTUAL_START_TIMER_ID)
    UPDATE_CONTEST_TIME_PERCENTAGE_BY_VIRTUAL_START_TIMER_ID = null
  }
  setup_update_contest_time_percentage_by_virtual_start()
}

$(() => {
  if (with_virtual_start) {
    $('.problem-cell[data-active-switcher="true"]').each(function() {
      var stat = $(this)
      update_score_penalty_result.call(stat, 'switcher')
      stat.children('.hidden').remove()
    })

    shuffle_statistics_rows()
    show_timeline()

    setup_update_contest_time_percentage_by_virtual_start()
    update_contest_time_percentage_by_virtual_start()

    visible_standings()
  }
})

/*
 * Upload solution
 */

$(() => {
  $('.drop-zone').on('dragover', function (e) {
    e.preventDefault()
    e.stopPropagation()
    $(this).addClass('dragover')
  })

  $('.drop-zone').on('dragleave', function (e) {
    e.preventDefault()
    e.stopPropagation()
    $(this).removeClass('dragover')
  })

  $('.drop-zone').on('drop', function (e) {
    e.preventDefault()
    e.stopPropagation()
    $(this).removeClass('dragover')

    const files = e.originalEvent.dataTransfer.files
    if (files.length > 1) {
      $.notify('Only one file can be uploaded', 'warn')
      return
    }

    if (!files.length) {
      return
    }
    standings_upload_solution(files[0], $(this))
  })

  function standings_upload_solution(file, problem_cell) {
    if (file.size > problem_user_solution_size_limit) {
      $.notify('File is too large', 'warn')
      return
    }

    const form_data = new FormData()
    form_data.append('file', file)
    form_data.append('pk', coder_pk)
    form_data.append('problem-short', problem_cell.closest('.problem-cell').data('problem-key'))
    form_data.append('statistic-id', problem_cell.closest('.stat-cell').data('statistic-id'))
    form_data.append('name', 'standings-upload-solution')
    $.ajax({
      type: 'POST',
      url: change_url,
      processData: false,
      contentType: false,
      data: form_data,
      beforeSend: function() { problem_cell.addClass('uploading') },
      success: function(data) { $.notify(data.message, data.status), location.reload() },
      error: log_ajax_error_callback,
      complete: function() { problem_cell.removeClass('uploading') },
    })
  }
});
