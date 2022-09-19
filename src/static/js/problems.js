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

$(function() {
  $('#show-tags').change(function() {
    if (coder_pk === undefined) {
      toggle_show_tags()
    } else {
      $.ajax({
        type: 'POST',
        url: '/settings/change/',
        data: {
          pk: coder_pk,
          name: 'show-tags',
          value: $(this).prop('checked'),
        },
        success: toggle_show_tags,
        error: log_ajax_error
      })
    }
    return false
  })
})
