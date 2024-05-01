$(function() {
  $('#contest').on('change', function() {
    var contest = $(this).val()
    $('button[value="start"]').attr('disabled', !contest)
  })

  $('.delete-virtual-start').on('click', function() {
    var virtual_start = $(this).closest('.virtual-start')
    var virtual_start_id = $(this).data('virtual-start-id')
    var contest_title = $(this).data('contest-title')

    bootbox.confirm({
      size: 'medium',
      message: 'Are you sure you want to delete the virtual start for <b>{contest_title}</b>?'.format({contest_title: contest_title}),
      callback: function(result) {
        if (result) {
          $.ajax({
            type: 'POST',
            url: change_url,
            data: {
              'pk': coder_pk,
              'name': 'delete-virtual-start',
              'id': virtual_start_id,
            },
            success: function(data) {
              virtual_start.remove()
            },
            error: function(data) {
              alert('{status} {statusText}'.format(data))
            },
          })
        }
      }
    })
  })

  $('.reset-virtual-start').on('click', function() {
    var virtual_start_id = $(this).data('virtual-start-id')
    var i = $(this).find('i')
    i.toggleClass('fa-spin')
    $.ajax({
      type: 'POST',
      url: change_url,
      data: {
        'pk': coder_pk,
        'name': 'reset-virtual-start',
        'id': virtual_start_id,
      },
      success: function(data) {
        window.location.reload()
      },
      error: log_ajax_error_callback,
      complete: function() {
        i.toggleClass('fa-spin')
      }
    })
  })
})
