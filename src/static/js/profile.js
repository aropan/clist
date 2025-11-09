function load_rating_history() {
  if (typeof ratings_url === 'undefined') {
    return
  }
  var loading_selector = '.loading-rating'
  $(loading_selector).toggleClass('hidden')
  $.ajax({
    url: ratings_url,
    method: 'GET',
    dataType: 'json',
    success: function (response) {
      var dates = response['data']['dates']
      combined_info = {
        'data': [],
        'datasets': {
          'labels': [],
        },
        'point_radius': 1,
        'border_width': 2,
        'without_before_draw': true,
        'without_highest': true,
        'cubic_interpolation_mode': 'monotone',
        'interaction_mode': 'nearest',
        'tooltip_mode': 'nearest',
        'legend_position': 'top',
        'title_display': false,
      }

      for (var resource in response['data']['resources']) {
        var resource_info = response['data']['resources'][resource]
        var resource_rating_id = 'resource_' + resource_info['pk']
        resource_rating_id += '_account_' + resource_info['account_pk']
        if (resource_info['kind']) {
          resource_rating_id += '_kind_' + resource_info['kind']
        }
        resource_rating_id += '_rating'

        var canvas = $('#' + resource_rating_id)
        if (!canvas.length) {
          continue
        }
        canvas.siblings(loading_selector).remove()
        config = create_chart_config(resource_info, dates)
        var label = resource_info['host']
        if (resource_info['kind']) {
          label += ' (' + resource_info['kind'] + ')'
        }
        combined_info['datasets']['labels'].push(label)
        combined_info['data'] = combined_info['data'].concat(resource_info['data'])
        combined_info['min'] = Math.min(combined_info['min'] || resource_info['min'], resource_info['min'])
        combined_info['max'] = Math.max(combined_info['max'] || resource_info['max'], resource_info['max'])

        var ctx = new Chart(resource_rating_id, config)
        add_selection_chart_range(resource_rating_id, ctx)

        if (!resource_info['kind']) {
          var resource_fields_id = 'resource_' + resource_info['pk'] + '_fields'
          add_selection_chart_fields(resource_info, resource_rating_id, resource_fields_id, dates)
        }
      }

      var n_combined = combined_info['data'].length
      var combined_id = 'combined_rating'
      var canvas = $('#' + combined_id)
      if (n_combined > 1 && canvas.length) {
        combined_info['datasets']['colors'] = palette('mpn65', n_combined).map(function (hex) { return '#' + hex; })
        config = create_chart_config(combined_info, dates)
        canvas.siblings(loading_selector).remove()
        var ctx = new Chart(combined_id, config)
        add_selection_chart_range(combined_id, ctx)
      }
    },
    error: function (data) {
      notify('{status} {statusText}'.format(data), 'error')
    },
    complete: function () {
      $(loading_selector).parent().remove()
    },
  })
}

$(function () {
  $('#expand-ratings').click(function () {
    $(this).closest('div.col-lg-6').removeClass('col-lg-6').addClass('col-xs-12')
    $('#list-accounts').closest('div.col-lg-6').removeClass('col-lg-6').addClass('col-xs-12')
    $('#collapse-history-resources').click()
    $(this).remove()
    event.preventDefault()
  })

  $('.update-account').click(function () {
    var btn = $(this)
    if (btn.attr('disabled')) {
      return
    }
    var icon = btn.find('i')
    icon.addClass('fa-spin')
    $.ajax({
      type: 'POST',
      url: change_url,
      data: {
        pk: coder_pk,
        name: 'update-account',
        id: $(this).attr('data-account-id'),
      },
      success: function (data) {
        btn.attr('data-original-title', '')
        btn.attr('disabled', 'disabled')
      },
      error: function (response) {
        icon.removeClass('fa-spin')
        log_ajax_error(response)
      },
    })
    event.preventDefault()
  })

  $('#verify-account').click(function () {
    var btn = $(this)
    btn.attr('disabled', 'disabled')
    btn.parent().height(btn.parent().height())
    var loading = $('#verify-loading')
    var error = $('#verify-error')
    btn.hide()
    error.addClass('hidden')
    loading.removeClass('hidden')

    $.ajax({
      url: verify_url,
      method: 'POST',
      data: { action: 'verify' },
      success: function (response) {
        btn.removeClass('btn-primary').addClass('btn-success')
        btn.text('Verified')
        btn.show()
        loading.addClass('hidden')
        notify('Verified', 'success')
        window.history.replaceState(null, null, account_url)
      },
      error: function (response) {
        btn.removeAttr('disabled')
        btn.show()
        loading.addClass('hidden')
        log_ajax_error(response, error)
      },
    })
  })
})
