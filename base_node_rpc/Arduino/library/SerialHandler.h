#include <NadaMQ.h>
#include <BaseHandler.h>


namespace base_node_rpc {

template <typename Stream>
struct serial_write_packet {
  Stream &output;

  serial_write_packet(Stream &stream) : output(stream) {}

  void operator()(UInt8Array data, uint8_t type_=Packet::packet_type::DATA) {
    FixedPacket to_send;
    to_send.type(type_);
    to_send.reset_buffer(data.length, data.data);
    to_send.payload_length_ = data.length;

    /* Set the CRC checksum of the packet based on the contents of the payload.
     * */
    to_send.compute_crc();

    stream_byte_type startflag[] = "|||";
    output.write(startflag, 3);
    serialize_any(output, to_send.iuid_);
    serialize_any(output, type_);
    if (to_send.type() == Packet::packet_type::DATA) {
      serialize_any(output, static_cast<uint16_t>(to_send.payload_length_));
      if (to_send.payload_length_ > 0) {
        output.write((stream_byte_type*)to_send.payload_buffer_,
                     to_send.payload_length_);
      }
      serialize_any(output, to_send.crc_);
    }
  }
};


template <typename Parser>
class SerialReceiver : public Receiver<Parser> {
public:
  typedef Receiver<Parser> base_type;
  using base_type::parser_;

  serial_write_packet<Stream> write_f_;

  SerialReceiver(Parser &parser) : base_type(parser), write_f_(Serial) {}

  void operator()(int16_t byte_count) {
    for (int i = 0; i < byte_count; i++) {
      uint8_t value = Serial.read();
      parser_.parse_byte(&value);
    }
  }
};


} // namespace base_node_rpc