package main

import (
	"bufio"
	"fmt"
	"os"
	"runtime/debug"
)

func main() {
	defer func() {
		if recovered := recover(); recovered != nil {
			fmt.Fprintf(os.Stderr, "[cr-worker] panic: %v\n%s\n", recovered, debug.Stack())
		}
	}()
	w := newWorker(os.Stdout)
	go w.idle()
	done := make(chan struct{})
	go func() {
		scanner := bufio.NewScanner(os.Stdin)
		scanner.Buffer(make([]byte, 64*1024), 4*1024*1024)
		for scanner.Scan() {
			line := append([]byte(nil), scanner.Bytes()...)
			c, err := decodeCommand(line)
			if err != nil {
				continue
			}
			go w.handle(c)
		}
		close(done)
	}()
	select {
	case <-w.stop:
	case <-done:
	}
	w.release("")
}
