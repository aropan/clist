function toggle_show_tags() {
  value = $('#show-tags').prop('checked')
  if (value) {
    $('.hidden-tag').addClass('hidden')
    $('.tag').removeClass('hidden')
  } else {
    $('.hidden-tag').removeClass('hidden')
    $('.tag').addClass('hidden')
  }
  $(window).trigger('resize')
}

function add_hidden_tag_event() {
  $('.unevent-hidden-tag').removeClass('unevent-hidden-tag').click(function() {
    $(this).addClass('hidden')
    $(this).siblings('.tag').removeClass('hidden')
    $(window).trigger('resize')
  })
}

function show_hidden_contests(e) {
  $(e).next().removeClass('hidden')
  $(e).remove()
  clear_tooltip()
  return false
}

$(function() {
  $('#show-tags').change(function() {
    if (coder_pk === undefined) {
      toggle_show_tags()
    } else {
      $.ajax({
        type: 'POST',
        url: change_url,
        data: {
          pk: coder_pk,
          name: 'show-tags',
          value: $(this).prop('checked'),
        },
        success: toggle_show_tags,
        error: function(response) {
          log_ajax_error(response)
        },
      })
    }
    return false
  })
})

function click_activity_problem_result(el) {
  $(el).siblings().removeClass('selected-activity')

  $(el).closest('tr').find('[data-solution-class]').each(function() {
    var solution_class = $(this).data('solution-class')
    if (solution_class) {
      $(this).removeClass(solution_class)
    }
    if ($(el).hasClass('selected-activity')) {
      if ($(el).hasClass('sol')) {
        solution_class = 'success'
      } else if ($(el).hasClass('rej')) {
        solution_class = 'danger'
      } else if ($(el).hasClass('tdo')) {
        solution_class = 'info'
      } else {
        solution_class = ''
      }
      $(this).data('solution-class', solution_class)
      if (solution_class) {
        $(this).addClass(solution_class)
      }
    } else {
      solution_class = $(this).data('system-solution-class')
    }
    $(this).data('solution-class', solution_class)
    if (solution_class) {
      $(this).addClass(solution_class)
    }
  })
}
