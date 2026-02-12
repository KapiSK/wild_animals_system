/* 文字サイズ */
$(function(){
	'use strict';
	if ($.cookie('style01')){
		switch($.cookie('style01')){
			case 'txt_normal': 
				$('#css_txt_size').attr({href:'/j/shared_new/shared/css/txt_normal.css'});
			break;
			case 'txt_big':
				$('#css_txt_size').attr({href:'/j/shared_new/shared/css/txt_big.css'});
			break;
		}
	}
});
/* 背景色 */
/*
$(function(){
	'use strict';
	if ($.cookie("style02")){
		switch($.cookie('style02')){
			case 'bg_normal': $('#bgcolor').attr({href:'/j/shared_new/shared/css/bg_normal.css'}); break;
			case 'bg_blue': $('#bgcolor').attr({href:'/j/shared_new/shared/css/bg_blue.css'}); break;
		}
	}
});
*/
function switchTxtsize(cssname){ //文字サイズCSSの変更、クッキーへ書き込み
	'use strict';
	var cssurl= '/j/shared_new/shared/css/'+cssname+'.css';
	$('#css_txt_size').attr({href:cssurl});
	$.cookie('style01',cssname,{expires:30,path:'/'});
}
/*
function switchBgcolor(cssname){ //背景CSSの変更、クッキーへ書き込み
	'use strict';
	var cssurl= '/j/shared_new/shared/css/'+cssname+'.css';
	$('#bgcolor').attr({href:cssurl});
	$.cookie('style02',cssname,{expires:30,path:'/'});
}
*/

/* プレースフォルダ */
$(function(){
	'use strict';
	$('.is_search_keyword').ahPlaceholder({
		placeholderColor : '#a0a0a0',
		placeholderAttr : 'title'
//		likeApple : true // テキストエリアに文字を入力し始めた時点でプレースホルダの文字が消える
	});
	$('.is_survey_txt').ahPlaceholder({
		placeholderColor : '#a0a0a0',
		placeholderAttr : 'title'
	});
});

/* ドロップダウンメニュー（PCメガメニュー） */
$(function(){
	'use strict';
	var gnavMegaCloseA = $('.gnav_nav-mega-close > a');
	var gnavNavLi = $('.gnav_nav > li');
	var gnavNavLiA = $('.gnav_nav > li > a');

	// リセット
	$(window).on('resize load', function(){
		var w = window.innerWidth;
		var x = 767;
		var z = 799;
		if (w > x){
			if (w < z){
				$('.gnav_nav').removeClass('is_gnav_nav');
				$('.gnav_btn_area').removeClass('is_gnav_btn_area');
				$('.gnav_btn').removeClass('is_gnav_btn');
				$('.gnav_nav li').removeClass('is_gnav_nav-current');
				$('.gnav_nav li a').removeClass('is_gnav_sp_mega_open');
				$('.gnav_nav li .gnav_nav-mega').removeClass('is_gnav_nav-mega is_gnav_sp_nav-mega');
			}
		}
	});

	gnavNavLiA.on({ // グロナビホバー
		'mouseenter.pcHover': function() {
			$(this).addClass('is_gnav_nav-current-hover');
		},
		'mouseleave.pcHover': function() {
			$(this).removeClass('is_gnav_nav-current-hover');
		}
	});

	gnavNavLiA.on('click.pcMega', function(){ // メガメニュー open/close
		if ($(this).next().hasClass('is_gnav_nav-mega')){
			// トグルボタン仕様
			$(this).next().removeClass('is_gnav_nav-mega');
			$(this).parent().removeClass('is_gnav_nav-current');
		} else {
			$(this).next().addClass('is_gnav_nav-mega');
			$(this).parent().addClass('is_gnav_nav-current');
			$(this).parent().siblings().removeClass('is_gnav_nav-current');
			$(this).parent().siblings().find('.gnav_nav-mega').removeClass('is_gnav_nav-mega');
		}
	});

	gnavMegaCloseA.on('click', function(e){ // メガメニューCloseボタン処理
		e.preventDefault();
//		$('.gnav_nav-mega').fadeOut(100);
		$(this).parent().parent().removeClass('is_gnav_nav-mega');
		gnavNavLi.removeClass('is_gnav_nav-current');
	});
});

/* テキストサイズ変更時にもmatchHeight（要素の高さを揃える）に反映させる */
$(function(){
	'use strict';
	var e = document.createElement("div");
	var s = document.createTextNode("dummy_textsize_trigger");
	e.appendChild(s);
	e.style.visibility='hidden';
	e.style.position='absolute';
	e.style.bottom='0';
	e.style.left='0';
	document.body.appendChild(e);
	var defHeight = e.offsetHeight;
	function checkBoxSize(){
		if(defHeight !== e.offsetHeight){
			$.fn.matchHeight._update();
			defHeight= e.offsetHeight;
		}
	}
	setInterval(checkBoxSize,300);
});

/* グロナビリンク無効 */
$(function(){
	'use strict';
	var gnavNavLiA = $('.gnav_nav > li > a');
	gnavNavLiA.on('click', function(e){ // グロナビリンク
		e.preventDefault();
//		return false;
	});
});

/* ページトップへ戻る */
$(function(){
	'use strict';
	var pageTop = $('.pnavi a');
	$('.pnavi').hide();
	pageTop.on('click touchend', function(){
		$('body, html').animate({scrollTop:0}, 500);
		return false;
	});
	$(window).on('load scroll', function(){
		// ブラウザ上部からxxxピクセル判定
		if ($(this).scrollTop() >= 400){
			pageTop.parent().fadeIn('fast');
		} else {
			pageTop.parent().fadeOut('fast');
		}
	});
});

// タブレット閲覧時グロナビのホバーを無効にする
$(function(){
	'use strict';
	var gnavNavLiA = $('.gnav_nav > li > a');
	if(navigator.userAgent.search("Android")>=0 || navigator.userAgent.search("iPhone")>=0 || navigator.userAgent.search("iPad")>=0){
		gnavNavLiA.off('.pcHover'); // グロナビホバーの名前空間.pcHoverを無効にする
	}
});

/* ２カラムに分けた項目の右マージンを削除（下層ページ） */
$(function(){
	'use strict';
	$('.column .column-item:nth-child(2n)').addClass('is_column-item');
});

/* GTM */
(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
})(window,document,'script','dataLayer','GTM-5T5KSV7');