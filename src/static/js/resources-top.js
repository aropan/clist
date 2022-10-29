function resources_top_setup_hover() {
  $(".to-hover[data-coder]").hover(
    function() {
      var coder = $(this).attr('data-coder')
      $("[data-coder='" + coder + "']").addClass('hover')
    },
    function() {
      var coder = $(this).attr('data-coder')
      $("[data-coder='" + coder + "']").removeClass('hover')
    },
  )
  $(".to-hover").click(
    function() {
      var coder = $(this).attr('data-coder')
      if (coder) {
        var elements = $("[data-coder='" + coder + "']")
        if ($(this).hasClass('fixed')) {
          elements.removeClass('fixed')
        } else {
          elements.addClass('fixed')
        }
      } else {
        $(this).toggleClass('fixed')
      }

      var coders = $('.fixed[data-coder]').map((_, el) => { pk = $(el).attr('data-coder'); return "coder_" + pk + "=" + pk })
      coders = [...new Set(coders)]
      var accounts = $('.fixed[data-account]').map((_, el) => { pk = $(el).attr('data-account'); return "account_" + pk + "=" + pk })
      accounts = [...new Set(accounts)]

      query = coders.concat(accounts)
      url = versus_url + '?redirect=&' + query.join('&')
      $('#versus-fixed').attr('disabled', query.length < 2).attr('href', url)
    }
  )
  $(".to-hover").removeClass('to-hover')
}

$(resources_top_setup_hover)
