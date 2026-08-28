package main

import "testing"

func TestCookieValueAcceptsRawAndCopiedCookie(t *testing.T) {
	if got := cookieValue("raw-value"); got != "raw-value" {
		t.Fatal(got)
	}
	if got := cookieValue("other=x; etp_rt=secret-value; Path=/"); got != "secret-value" {
		t.Fatal(got)
	}
}
